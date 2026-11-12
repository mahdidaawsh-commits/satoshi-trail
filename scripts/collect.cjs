const fs = require('node:fs');
const path = require('node:path');
const {root, assert, digest, equal, sourceHash, receiptSummary, save} = require('./transport.cjs');
const fixture = require('../fixtures/bitcoin.json');

const runs = process.argv.slice(2);
const cases = {
  legacy: ['deploy', 'premature-retire', 'wrong-script', 'credit', 'duplicate-credit',
    'unrelated-spend', 'retire', 'duplicate-retire'],
  segwit: ['deploy', 'credit', 'duplicate-credit'],
};
const errors = {
  'premature-retire': 'Outpoint not imported', 'wrong-script': 'Output does not match watch script',
  'duplicate-credit': 'Outpoint already imported', 'unrelated-spend': 'Transaction does not spend outpoint',
  'duplicate-retire': 'Outpoint already retired',
};
const explorer = 'https://explorer-studio.genlayer.com/';
const repo = 'https://github.com/mahdidaawsh-commits/satoshi-trail';
assert(runs.length === 2 && runs.every(id => /^\d+$/.test(id)) && runs[0] !== runs[1],
  'Pass the completed legacy and SegWit run IDs');

const instances = [];
const files = [];
let successes = 0;
let rejections = 0;
for (const [i, [scenario, labels]] of Object.entries(cases).entries()) {
  const folder = path.join(root, '.proof-journal', 'run-' + runs[i]);
  const read = label => JSON.parse(fs.readFileSync(path.join(folder, scenario + '-' + label + '.json')));
  const report = read('verified');
  assert(report.scenario === scenario && report.source_sha256 === sourceHash, 'Proof source mismatch');
  assert(equal(report.trace.map(step => step.label), labels), 'Unexpected receipt order');
  let previous;
  for (const step of report.trace) {
    const raw = read(step.label + '-receipt');
    const summary = receiptSummary(raw);
    assert(summary.hash === step.hash && summary.status === 'FINALIZED' && summary.result === 'MAJORITY_AGREE'
      && summary.agree > (summary.agree + summary.disagree + summary.idle) / 2, 'Finalized strict majority required');
    assert((raw.from_address || raw.sender).toLowerCase() === step.signer
      && (raw.to_address || raw.recipient).toLowerCase() === report.contract.toLowerCase(), 'Receipt identity mismatch');
    if (step.label === 'deploy') {
      assert(summary.hash === report.deployment && digest(Buffer.from(raw.data.contract_code, 'base64')) === sourceHash,
        'Deployment source mismatch');
    }
    const error = errors[step.label];
    if (error) {
      const payload = Buffer.from(raw.consensus_data.leader_receipt[0].result, 'base64');
      assert(summary.execution === 'ERROR' && payload[0] === 1 && payload.subarray(1).toString() === error
        && equal(step.state, previous), 'Expected rejection with unchanged state');
      rejections++;
    } else {
      assert(['SUCCESS', 'FINISHED_WITH_RETURN'].includes(summary.execution), 'Expected successful execution');
      successes++;
    }
    const totals = step.state.totals;
    assert(totals.unretired_sats + totals.retired_sats === totals.imported_sats, 'Satoshi conservation failed');
    previous = step.state;
    files.push([scenario + '-' + step.label + '-receipt', raw]);
  }
  const credit = report.trace.find(step => step.label === 'credit');
  const retire = report.trace.find(step => step.label === 'retire');
  assert(credit.signer !== report.trace[0].signer, 'Permissionless credit not exercised');
  const {created, spent} = previous.entry;
  const tx = fixture[scenario];
  assert(created.txid === tx.txid && created.vout === 0 && created.sats === tx.outputs[0][0]
    && created.block_hash === tx.block && created.height === tx.proof.block_height, 'Wrong creation anchor');
  if (scenario === 'legacy') {
    assert(spent.txid === fixture.spender.txid && spent.block_hash === fixture.spender.block
      && previous.totals.unretired_sats === 0, 'Missing verified retirement');
  } else {
    assert(spent === null && previous.totals.unretired_sats === 311000, 'Wrong SegWit ledger totals');
  }
  instances.push({scenario, contract: report.contract, deployment: report.deployment, credit: credit.hash,
    retire: retire?.hash ?? null, created, spent, totals: previous.totals, workflow: repo + '/actions/runs/' + runs[i]});
  files.push([scenario + '-verified', report]);
}

for (const [name, value] of files) save(name, value);
save('index', {source_sha256: sourceHash, successes, rejections, instances});
const rows = instances.map(x => '| ' + [
  x.scenario, '[Contract](' + explorer + 'address/' + x.contract + ')',
  '[Deploy](' + explorer + 'tx/' + x.deployment + ')',
  '[Credit](' + explorer + 'tx/' + x.credit + ')',
  x.retire ? '[Retire](' + explorer + 'tx/' + x.retire + ')' : '—',
  '[Run](' + x.workflow + ')',
].join(' | ') + ' |');
fs.writeFileSync(path.join(root, 'proofs/README.md'), [
  '# SatoshiTrail StudioNet proofs', '',
  'Verified ' + (successes + rejections) + ' finalized receipts across two deployments, with '
    + successes + ' successful calls and ' + rejections + ' expected rejections.', '',
  '| Scenario | Address | Deployment | Credit | Retirement | Workflow |',
  '|---|---|---|---|---|---|', ...rows, '',
  'The legacy ledger credited and retired 1,000,000,000 satoshis from Bitcoin heights 170 and 92240.',
  'The SegWit ledger credited 311,000 satoshis from height 481824.', '',
  '[Bitcoin legacy payment](https://mempool.space/tx/' + fixture.legacy.txid + ') · '
    + '[Bitcoin spend](https://mempool.space/tx/' + fixture.spender.txid + ') · '
    + '[Bitcoin SegWit payment](https://mempool.space/tx/' + fixture.segwit.txid + ')', '',
  'Source SHA-256: `' + sourceHash + '`.', '',
].join('\n'));
console.log(JSON.stringify({sourceHash, successes, rejections, instances}, null, 2));
