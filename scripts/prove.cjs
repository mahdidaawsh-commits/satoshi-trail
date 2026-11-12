const fs = require('node:fs');
const path = require('node:path');
const {root, assert, equal, sourceHash, invoke, read, rpc, receipt, receiptSummary, save} = require('./transport.cjs');
const {decodeReceipt} = require('./receipt-calldata.cjs');
const data = require('../fixtures/bitcoin.json');

async function main() {
  const scenario = process.env.TRAIL_SCENARIO;
  assert(['legacy', 'segwit'].includes(scenario), 'Choose a supported scenario');
  const prefix = scenario + '-';
  const wallets = JSON.parse(process.env.TRAIL_ACCOUNTS || '[]');
  assert(wallets.length === 2 && wallets[0].address !== wallets[1].address, 'Two distinct wallets required');
  const code = fs.readFileSync(path.join(root, 'contracts/satoshi_trail.py'));
  const {txid, outputs, proof, block} = data[scenario];
  const [sats, script] = outputs[0];
  const expected = {script, imported_sats: 0, retired_sats: 0, unretired_sats: 0, credits: 0, retirements: 0};
  let expectedEntry = {};
  assert(await rpc('eth_chainId', []) === '0xf22f', 'StudioNet only');

  process.env.TRAIL_ACCOUNT = wallets[0].name;
  const deployment = await invoke(prefix + 'deploy', ['deploy', '--contract', 'contracts/satoshi_trail.py', '--args', script]);
  const deployed = await receipt(prefix + 'deploy', deployment, true);
  const contract = deployed.to_address || deployed.recipient;
  assert(/^0x[0-9a-f]{40}$/i.test(contract), 'Missing deployed address');
  assert(code.equals(Buffer.from(deployed.data.contract_code, 'base64')), 'Deployed source mismatch');
  const report = {scenario, contract, deployment, source_sha256: sourceHash, trace: []};

  async function verify(label, raw, actor, args, error = null) {
    const info = receiptSummary(raw);
    assert((raw.from_address || raw.sender).toLowerCase() === wallets[actor].address, 'Wrong receipt sender');
    assert((raw.to_address || raw.recipient).toLowerCase() === contract.toLowerCase(), 'Wrong receipt recipient');
    assert(equal(await decodeReceipt(raw), args), 'Unexpected signed calldata');
    if (error) {
      const payload = Buffer.from(raw.consensus_data.leader_receipt[0].result, 'base64');
      assert(payload[0] === 1 && payload.subarray(1).toString() === error, 'Wrong revert reason: ' + label);
    }
    const totals = await read(prefix + label + '-totals', ['call', contract, 'get_totals']);
    const entry = await read(prefix + label + '-entry', ['call', contract, 'get_output', '--args', txid, '0']);
    if (!equal(totals, expected) || !equal(entry, expectedEntry)) {
      save(prefix + 'state-mismatch', {label, totals, entry, expected, expectedEntry});
    }
    assert(equal(totals, expected) && equal(entry, expectedEntry), 'Unexpected state after ' + label);
    report.trace.push({label, ...info, signer: wallets[actor].address, args, error, state: {totals, entry}});
    save(prefix + 'progress', report);
  }
  await verify('deploy', deployed, 0, {args: [script]});

  async function write(label, actor, method, args, error, update = () => {}) {
    process.env.TRAIL_ACCOUNT = wallets[actor].name;
    const hash = await invoke(prefix + label, ['write', contract, method, '--args', ...args.map(String)]);
    const raw = await receipt(prefix + label, hash, !error);
    update();
    await verify(label, raw, actor, {method, args}, error);
  }
  if (scenario === 'legacy') {
    await write('premature-retire', 1, 'retire_output', [txid, 0, data.spender.txid], 'Outpoint not imported');
    await write('wrong-script', 1, 'import_output', [txid, 1], 'Output does not match watch script');
  }
  await write('credit', 1, 'import_output', [txid, 0], null, () => {
    expectedEntry = {created: {txid, height: proof.block_height, block_hash: block, position: proof.pos,
      vout: 0, sats, script}, spent: null};
    expected.imported_sats = sats;
    expected.unretired_sats = sats;
    expected.credits = 1;
  });
  await write('duplicate-credit', 0, 'import_output', [txid, 0], 'Outpoint already imported');
  if (scenario === 'legacy') {
    await write('unrelated-spend', 0, 'retire_output', [txid, 0, data.segwit.txid], 'Transaction does not spend outpoint');
    const spend = data.spender;
    assert(equal(spend.inputs[0], [txid, 0]), 'Fixture does not spend the tracked output');
    await write('retire', 0, 'retire_output', [txid, 0, spend.txid], null, () => {
      expectedEntry.spent = {txid: spend.txid, height: spend.proof.block_height, block_hash: spend.block,
        position: spend.proof.pos, vin: 0};
      expected.retired_sats = sats;
      expected.unretired_sats = 0;
      expected.retirements = 1;
    });
    await write('duplicate-retire', 1, 'retire_output', [txid, 0, spend.txid], 'Outpoint already retired');
  }
  assert(code.equals(Buffer.from(await rpc('gen_getContractCode', [contract]), 'base64')), 'Fresh source read mismatch');
  save(prefix + 'verified', report);
  console.log(JSON.stringify({scenario, contract, deployment, receipts: report.trace.length, totals: expected}));
}

main().catch(error => { console.error(error.stack); process.exitCode = 1; });
