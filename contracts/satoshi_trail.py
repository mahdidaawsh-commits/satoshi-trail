# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from hashlib import sha256
import json
import re


RELAYS = ('https://blockstream.info/api', 'https://mempool.space/api')
HASH = r'[0-9a-f]{64}'
MAX_MONEY = 21_000_000 * 100_000_000
MAX_SIZE = 16_384
MAX_IO = 128
CONFIRMATIONS = 6
POW_LIMIT = 0xFFFF << 208


def fail(message):
    raise gl.vm.UserError(message)


def hash256(raw):
    return sha256(sha256(raw).digest()).digest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class Reader:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, length):
        start = self.offset
        end = start + length
        if end > len(self.raw):
            fail('Truncated Bitcoin transaction')
        self.offset = end
        return self.raw[start:end]

    def uint(self, length):
        return int.from_bytes(self.take(length), 'little')

    def compact(self, limit):
        first = self.uint(1)
        if first < 253:
            value = first
        else:
            width = {253: 2, 254: 4, 255: 8}[first]
            value = self.uint(width)
            if value < {2: 253, 4: 65536, 8: 4294967296}[width]:
                fail('Noncanonical CompactSize')
        if value > limit:
            fail('Bitcoin transaction exceeds bounds')
        return value


def parse_transaction(raw, expected_txid):
    if not 10 <= len(raw) <= MAX_SIZE:
        fail('Invalid transaction size')
    reader = Reader(raw)
    version = reader.take(4)
    segwit = raw[4] == 0
    if segwit and reader.take(2) != b'\x00\x01':
        fail('Invalid witness marker')
    body_start = reader.offset
    input_count = reader.compact(MAX_IO)
    if input_count == 0:
        fail('Empty inputs')
    inputs = []
    for _ in range(input_count):
        txid = reader.take(32)[::-1].hex()
        index = reader.uint(4)
        reader.take(reader.compact(10_000))
        reader.take(4)
        inputs.append([txid, index])
    output_count = reader.compact(MAX_IO)
    if output_count == 0:
        fail('Empty outputs')
    outputs = []
    total = 0
    for _ in range(output_count):
        sats = reader.uint(8)
        total += sats
        if total > MAX_MONEY:
            fail('Invalid Bitcoin amount')
        script = reader.take(reader.compact(10_000)).hex()
        outputs.append([sats, script])
    body_end = reader.offset
    if segwit:
        has_witness = False
        for _ in range(input_count):
            count = reader.compact(MAX_IO)
            has_witness = has_witness or count > 0
            for _ in range(count):
                reader.take(reader.compact(MAX_SIZE))
        if not has_witness:
            fail('Empty witness serialization')
    locktime = reader.take(4)
    if reader.offset != len(raw):
        fail('Trailing Bitcoin transaction bytes')
    stripped = version + raw[body_start:body_end] + locktime
    # A 64-byte leaf can be confused with a pair of internal Merkle nodes.
    if len(stripped) == 64:
        fail('Ambiguous Bitcoin Merkle leaf')
    if hash256(stripped)[::-1].hex() != expected_txid:
        fail('Bitcoin txid mismatch')
    return inputs, outputs


def verify_header(header, block_hash):
    if len(header) != 80 or hash256(header)[::-1].hex() != block_hash:
        fail('Bitcoin header hash mismatch')
    compact = int.from_bytes(header[72:76], 'little')
    exponent, mantissa = compact >> 24, compact & 0x7FFFFF
    if compact & 0x800000 or not 3 <= exponent <= 32 or mantissa == 0:
        fail('Invalid Bitcoin work target')
    target = mantissa << (8 * (exponent - 3))
    if target > POW_LIMIT or int(block_hash, 16) > target:
        fail('Bitcoin header fails proof of work')


def verify_branch(txid, position, branch, root):
    node = bytes.fromhex(txid)[::-1]
    for sibling in branch:
        other = bytes.fromhex(sibling)[::-1]
        node = hash256(other + node) if position & 1 else hash256(node + other)
        position >>= 1
    if position or node != root:
        fail('Bitcoin Merkle root mismatch')


def fetch(host, route, max_length):
    try:
        response = gl.nondet.web.get(host + route)
        if response.status != 200 or len(response.body) > max_length:
            fail('Bitcoin evidence unavailable or oversized')
        return response.body.decode('ascii').strip()
    except Exception:
        fail('Bitcoin evidence unavailable or oversized')


def checked_hex(text, max_length):
    if not text or len(text) > max_length or len(text) % 2 or not re.fullmatch(r'[a-fA-F0-9]+', text):
        fail('Invalid Bitcoin hex')
    return bytes.fromhex(text)


def canonical_block(height):
    route = '/block-height/' + str(height)
    block_hash = fetch(RELAYS[0], route, 66)
    if not re.fullmatch(HASH, block_hash) or fetch(RELAYS[1], route, 66) != block_hash:
        fail('Bitcoin relays disagree on block')
    return block_hash


def verified_transaction(txid):
    primary = RELAYS[0]
    path = '/tx/' + txid
    raw = checked_hex(fetch(primary, path + '/hex', 2 * MAX_SIZE + 2), 2 * MAX_SIZE)
    inputs, outputs = parse_transaction(raw, txid)
    try:
        proof = json.loads(fetch(primary, path + '/merkle-proof', 4096))
    except ValueError:
        fail('Invalid Bitcoin Merkle proof')
    if not isinstance(proof, dict):
        fail('Invalid Bitcoin Merkle proof')
    height, position, branch = proof.get('block_height'), proof.get('pos'), proof.get('merkle')
    if (type(height) is not int or not 1 <= height <= 10_000_000 or type(position) is not int
            or position < 0 or not isinstance(branch, list) or len(branch) > 24
            or position >= 1 << len(branch)
            or any(not isinstance(x, str) or not re.fullmatch(HASH, x) for x in branch)):
        fail('Invalid Bitcoin Merkle proof')
    block_hash = canonical_block(height)
    for host in RELAYS:
        tip = fetch(host, '/blocks/tip/height', 12)
        if not re.fullmatch(r'[0-9]{1,8}', tip) or int(tip) - height + 1 < CONFIRMATIONS:
            fail('Bitcoin output is not deep enough')
    header = checked_hex(fetch(primary, '/block/' + block_hash + '/header', 162), 160)
    verify_header(header, block_hash)
    verify_branch(txid, position, branch, header[36:68])
    return {'txid': txid, 'height': height, 'block_hash': block_hash, 'position': position}, inputs, outputs


def verifier(sample):
    def validate(leader):
        try:
            local = sample()
        except gl.vm.UserError as error:
            return (not isinstance(leader, gl.vm.Return)
                    and getattr(leader, 'message', None) == error.message)
        except Exception:
            return False
        return isinstance(leader, gl.vm.Return) and local == leader.calldata

    return validate


def observe_output(txid, index, watch_script):
    def sample():
        inclusion, inputs, outputs = verified_transaction(txid)
        if inputs == [['0' * 64, 0xFFFFFFFF]]:
            fail('Coinbase outputs are unsupported')
        if index >= len(outputs):
            fail('Missing Bitcoin output')
        value, script = outputs[index]
        if script != watch_script or value == 0:
            fail('Output does not match watch script')
        return {**inclusion, 'vout': index, 'sats': value, 'script': script}

    return gl.vm.run_nondet_unsafe(sample, verifier(sample))


def observe_spend(txid, created):
    def sample():
        inclusion, inputs, _ = verified_transaction(txid)
        target = [created['txid'], created['vout']]
        if target not in inputs:
            fail('Transaction does not spend outpoint')
        if ((inclusion['height'], inclusion['position']) <= (created['height'], created['position'])
                or (inclusion['height'] == created['height'] and inclusion['block_hash'] != created['block_hash'])):
            fail('Spend does not follow creation')
        if inclusion['height'] != created['height'] and canonical_block(created['height']) != created['block_hash']:
            fail('Creation block is no longer canonical')
        return {**inclusion, 'vin': inputs.index(target)}

    return gl.vm.run_nondet_unsafe(sample, verifier(sample))


def outpoint(txid, index):
    if not re.fullmatch(HASH, txid) or type(index) is not int or not 0 <= index < MAX_IO:
        fail('Invalid outpoint')
    return txid + ':' + str(index)


class SatoshiTrail(gl.Contract):
    script: str
    outputs: TreeMap[str, str]
    imported_sats: u256
    retired_sats: u256
    credits: u256
    retirements: u256

    def __init__(self, watch_script: str):
        if not re.fullmatch(r'(?:[0-9a-f]{2}){1,128}', watch_script):
            fail('Invalid watch script')
        self.script = watch_script
        self.imported_sats = u256(0)
        self.retired_sats = u256(0)
        self.credits = u256(0)
        self.retirements = u256(0)

    @gl.public.write
    def import_output(self, txid: str, index: int) -> None:
        key = outpoint(txid, index)
        if key in self.outputs:
            fail('Outpoint already imported')
        created = observe_output(txid, index, self.script)
        self.outputs[key] = encode({'created': created, 'spent': None})
        self.imported_sats = u256(int(self.imported_sats) + created['sats'])
        self.credits = u256(int(self.credits) + 1)

    @gl.public.write
    def retire_output(self, txid: str, index: int, spender: str) -> None:
        key = outpoint(txid, index)
        if key not in self.outputs:
            fail('Outpoint not imported')
        entry = json.loads(self.outputs[key])
        if entry['spent'] is not None:
            fail('Outpoint already retired')
        if not re.fullmatch(HASH, spender) or spender == txid:
            fail('Invalid spending transaction')
        entry['spent'] = observe_spend(spender, entry['created'])
        self.outputs[key] = encode(entry)
        self.retired_sats = u256(int(self.retired_sats) + entry['created']['sats'])
        self.retirements = u256(int(self.retirements) + 1)

    @gl.public.view
    def get_output(self, txid: str, index: int) -> dict:
        key = outpoint(txid, index)
        return json.loads(self.outputs[key]) if key in self.outputs else {}

    @gl.public.view
    def get_totals(self) -> dict:
        imported, retired = int(self.imported_sats), int(self.retired_sats)
        return {'script': self.script, 'imported_sats': imported, 'retired_sats': retired,
                'unretired_sats': imported - retired, 'credits': int(self.credits),
                'retirements': int(self.retirements)}
