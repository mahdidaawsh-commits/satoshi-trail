Category: Builder → Intelligent Contracts

Title: SatoshiTrail: Bitcoin outpoint accounting with independent proof verification

Notes / Description:

SatoshiTrail keeps a Bitcoin outpoint ledger for a fixed script. Leader and validators independently retrieve raw transactions, Merkle proofs, block headers and chain evidence. Two relays must agree on the canonical block and each must report at least six confirmations. The contract recomputes the txid, header hash, proof of work and Merkle root. It parses legacy and SegWit transaction bytes to obtain the actual amount and script or verify the exact spending input. Agreement on those facts credits or retires the satoshi amount once. Ledger entries link both transactions and their blocks. Unretired totals cover imported outputs whose spend has yet to be recorded.
