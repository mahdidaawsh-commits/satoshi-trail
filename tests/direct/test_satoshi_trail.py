from hashlib import sha256
import json
from pathlib import Path
import re

import pytest


DATA = json.loads((Path(__file__).resolve().parents[2] / 'fixtures/bitcoin.json').read_text())
PRIMARY = 'https://blockstream.info/api'
SECONDARY = 'https://mempool.space/api'
SOURCE = 'contracts/satoshi_trail.py'


def sample(vm, *names, override=None):
    responses = {host + '/blocks/tip/height': '1000000' for host in (PRIMARY, SECONDARY)}
    for name in names:
        tx = DATA[name]
        path = PRIMARY + '/tx/' + tx['txid']
        responses[path + '/hex'] = tx['hex']
        responses[path + '/merkle-proof'] = json.dumps(tx['proof'])
        responses[PRIMARY + '/block/' + tx['block'] + '/header'] = tx['header']
        for host in (PRIMARY, SECONDARY):
            responses[host + '/block-height/' + str(tx['proof']['block_height'])] = tx['block']
    responses.update(override or {})
    vm.clear_mocks()
    for url, body in responses.items():
        vm.mock_web('^' + re.escape(url) + '$', {'status': 200, 'body': body.encode()})


def deploy(direct_deploy, name='legacy'):
    return direct_deploy(SOURCE, DATA[name]['outputs'][0][1], sdk_version='v0.2.16')


def test_legacy_output_and_actual_spend_conserve_satoshis(direct_vm, direct_deploy, direct_accounts):
    ledger = deploy(direct_deploy)
    tx, spend = DATA['legacy']['txid'], DATA['spender']['txid']
    sample(direct_vm, 'legacy', 'spender')
    direct_vm.sender = direct_accounts[1]
    ledger.import_output(tx, 0)
    assert direct_vm.run_validator() is True
    created = ledger.get_output(tx, 0)['created']
    assert created['sats'] == 1_000_000_000 and created['height'] == 170
    assert ledger.get_totals()['unretired_sats'] == 1_000_000_000
    with direct_vm.expect_revert('Outpoint already imported'):
        ledger.import_output(tx, 0)
    direct_vm.sender = direct_accounts[2]
    ledger.retire_output(tx, 0, spend)
    assert direct_vm.run_validator() is True
    record = ledger.get_output(tx, 0)
    assert record['created'] == created
    assert record['spent']['txid'] == spend and record['spent']['vin'] == 0
    totals = ledger.get_totals()
    assert totals['imported_sats'] == totals['retired_sats'] == 1_000_000_000
    assert totals['credits'] == totals['retirements'] == 1 and totals['unretired_sats'] == 0
    with direct_vm.expect_revert('Outpoint already retired'):
        ledger.retire_output(tx, 0, spend)
    assert ledger.get_totals() == totals


def test_segwit_uses_witness_stripped_txid(direct_vm, direct_deploy):
    ledger = deploy(direct_deploy, 'segwit')
    tx = DATA['segwit']
    raw = bytes.fromhex(tx['hex'])
    wtxid = sha256(sha256(raw).digest()).digest()[::-1].hex()
    assert raw[4:6] == b'\x00\x01' and wtxid != tx['txid']
    sample(direct_vm, 'segwit')
    ledger.import_output(tx['txid'], 0)
    assert direct_vm.run_validator() is True
    assert ledger.get_output(tx['txid'], 0)['created']['sats'] == tx['outputs'][0][0]
    assert ledger.get_totals()['unretired_sats'] == 311_000


@pytest.mark.parametrize(('kind', 'reason'), [
    ('raw', 'Bitcoin txid mismatch'),
    ('branch', 'Bitcoin Merkle root mismatch'),
    ('header', 'Bitcoin header hash mismatch'),
    ('canonical', 'Bitcoin relays disagree on block'),
    ('tip', 'Bitcoin output is not deep enough'),
])
def test_invalid_evidence_never_credits(direct_vm, direct_deploy, kind, reason):
    ledger = deploy(direct_deploy)
    tx = DATA['legacy']
    base = PRIMARY + '/tx/' + tx['txid']
    cases = {
        'raw': {base + '/hex': tx['hex'][:-2] + '01'},
        'branch': {base + '/merkle-proof': json.dumps({**tx['proof'], 'merkle': ['1' * 64]})},
        'header': {PRIMARY + '/block/' + tx['block'] + '/header': '02' + tx['header'][2:]},
        'canonical': {SECONDARY + '/block-height/170': '2' * 64},
        'tip': {SECONDARY + '/blocks/tip/height': '174'},
    }
    sample(direct_vm, 'legacy', override=cases[kind])
    with direct_vm.expect_revert(reason):
        ledger.import_output(tx['txid'], 0)
    assert ledger.get_output(tx['txid'], 0) == {}
    assert ledger.get_totals()['credits'] == 0


def test_validator_rechecks_exact_confirmation_threshold(direct_vm, direct_deploy):
    ledger = deploy(direct_deploy)
    tx = DATA['legacy']['txid']
    sample(direct_vm, 'legacy', override={SECONDARY + '/blocks/tip/height': '175'})
    ledger.import_output(tx, 0)
    assert direct_vm.run_validator() is True
    sample(direct_vm, 'legacy', override={SECONDARY + '/blocks/tip/height': '174'})
    assert direct_vm.run_validator() is False
    sample(direct_vm, 'legacy', override={SECONDARY + '/blocks/tip/height': '176'})
    assert direct_vm.run_validator() is True


def test_unrelated_transaction_cannot_retire_an_output(direct_vm, direct_deploy):
    ledger = deploy(direct_deploy)
    tx = DATA['legacy']['txid']
    sample(direct_vm, 'legacy', 'segwit')
    with direct_vm.expect_revert('Output does not match watch script'):
        ledger.import_output(tx, 1)
    ledger.import_output(tx, 0)
    before = ledger.get_totals()
    with direct_vm.expect_revert('Transaction does not spend outpoint'):
        ledger.retire_output(tx, 0, DATA['segwit']['txid'])
    assert ledger.get_totals() == before
    assert ledger.get_output(tx, 0)['spent'] is None


def test_retirement_rechecks_original_block(direct_vm, direct_deploy):
    ledger = deploy(direct_deploy)
    tx = DATA['legacy']['txid']
    sample(direct_vm, 'legacy')
    ledger.import_output(tx, 0)
    sample(direct_vm, 'spender', override={host + '/block-height/170': '1' * 64
                                          for host in (PRIMARY, SECONDARY)})
    with direct_vm.expect_revert('Creation block is no longer canonical'):
        ledger.retire_output(tx, 0, DATA['spender']['txid'])
    assert ledger.get_totals()['retirements'] == 0


def test_64_byte_transaction_does_not_enter_merkle_verification(direct_vm, direct_deploy):
    ledger = deploy(direct_deploy)
    raw = bytes.fromhex('0100000001' + '22' * 32 + '0000000000ffffffff01'
                        + '0100000000000000045151515100000000')
    assert len(raw) == 64
    txid = sha256(sha256(raw).digest()).digest()[::-1].hex()
    sample(direct_vm, override={PRIMARY + '/tx/' + txid + '/hex': raw.hex()})
    with direct_vm.expect_revert('Ambiguous Bitcoin Merkle leaf'):
        ledger.import_output(txid, 0)
    assert ledger.get_totals()['credits'] == 0
