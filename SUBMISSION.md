Category: Builder → Intelligent Contracts

Title: SatoshiTrail: Bitcoin outpoint accounting with independent proof verification

Notes / Description:

SatoshiTrail tracks Bitcoin outpoints for a fixed script. Leader and validators independently fetch raw transactions, Merkle proofs and block headers. Two relays must agree on the canonical block and each must report six or more confirmations. The contract recomputes the txid, header hash, proof of work and Merkle root, then reads the actual amount and script or verifies the exact spending input. Agreement credits or retires the recorded satoshis once. Unretired totals cover imported outputs whose spends have yet to be recorded. GenVM lint and 18 tests passed. Two StudioNet deployments verified 11 finalized receipts using real Bitcoin mainnet data, including legacy credit and retirement, SegWit credit, and six expected rejections.

Evidence: [Contract source](contracts/satoshi_trail.py) · [StudioNet legacy ledger](https://explorer-studio.genlayer.com/address/0x07F54a1377234e3f2EDB31aa7CFC6C2Cf3622Dc4) · [Onchain proofs](proofs/README.md)
