# SatoshiTrail

SatoshiTrail tracks Bitcoin mainnet outpoints for one fixed output script.
Any caller can import a matching output and later retire it with proof of the
transaction that spent it. The ledger records the credited and retired
satoshis separately and links each entry to its Bitcoin block and transaction.
It never moves Bitcoin or creates transferable balances.

## Evidence and consensus

For either write, the leader and validators independently retrieve the raw
transaction, Merkle branch and block header. Blockstream and mempool.space must
agree on the canonical block hash at the proof height, and each reported tip
must give it at least six confirmations. The contract recomputes the transaction
ID, header hash, advertised proof of work and Merkle root. It reads the output
script and amount or the spending input from the transaction bytes. Consensus
compares the exact verified fields used to change the ledger. Reported tips
may differ when both meet the same threshold.

The parser handles legacy transactions and computes SegWit transaction IDs
from the witness-stripped serialization. It bounds raw size, counts and
scripts, and excludes 64-byte stripped transactions from Merkle verification.
The block header and Merkle branch verify inclusion. Canonical chain and tip
selection rely on the two HTTPS sources. Bitcoin script execution and
chainwide work comparison are the responsibility of those sources.

## State and use

Deploy with a lowercase, hex-encoded Bitcoin output script. Call
`import_output(txid, vout)` to record its value from a matching non-coinbase
output. Call `retire_output(txid, vout, spender)` to record an exact spending
input and retire the credited amount once. Retirement checks that the
creation block is still canonical and that the spend follows creation.
`get_output(txid, vout)` gives the two proof anchors. `get_totals()` reports
imported, retired and unretired satoshis. Unretired means a spend has yet to
be recorded here. The ledger covers submitted outpoints, and a deep Bitcoin
reorganization can leave an older entry requiring reconciliation offchain.

Fixtures use actual Bitcoin mainnet transactions at heights 170, 92240 and
481824. The StudioNet workflows exercise legacy credit and retirement, SegWit
credit, wrong-script and unrelated-spend rejection, and duplicate calls.
They compare exact source bytes and re-read the ledger after every transaction.

References: [Esplora API](https://github.com/Blockstream/esplora/blob/master/API.md) ·
[Bitcoin block header and Merkle format](https://developer.bitcoin.org/reference/block_chain.html) ·
[SegWit txid rules](https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki) ·
[GenLayer Equivalence Principle](https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle)

```sh
pip install -r requirements-dev.txt
genvm-lint download --version v0.2.16
genvm-lint check contracts/satoshi_trail.py
python -m pytest tests/direct -q
node --test tests/rpc-preflight.test.cjs
```

Generic CLI transport and test signing helpers are reused under MIT from
[ArchiveLift](https://github.com/gabrieladash123-bit/archive-lift).
