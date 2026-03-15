/**
 * TipMind WDK Microservice
 * ─────────────────────────────────────────────────────────────────────────────
 * Wraps Tether's @tetherto/wdk Node.js SDK and exposes a clean REST API
 * so the Python FastAPI backend can execute real on-chain USDT tips.
 *
 * Endpoints:
 *   POST /send          { to, amount, token }  → { tx_hash, fee, from, status }
 *   GET  /balance       ?token=USDT            → { balance, token, address }
 *   GET  /address                              → { address }
 *   GET  /tx/:hash                             → { status, hash }
 *   GET  /health                               → { status, address, chain }
 *
 * Env vars (in root .env):
 *   WDK_SEED_PHRASE     — 12-word BIP39 mnemonic
 *   WDK_RPC_URL         — Polygon/Ethereum RPC (default: Polygon public)
 *   WDK_CHAIN           — "polygon" | "ethereum" (default: polygon)
 *   WDK_SERVICE_PORT    — HTTP port (default: 3001)
 *   WDK_API_KEY         — Bearer token for auth between Python↔this service
 *
 * USDT contract addresses:
 *   Polygon mainnet  0xc2132D05D31c914a87C6611C10748AEb04B58e8F  (6 decimals)
 *   Ethereum mainnet 0xdAC17F958D2ee523a2206206994597C13D831ec7  (6 decimals)
 */

import 'dotenv/config';
import express from 'express';
import { ethers } from 'ethers';
import WDK from '@tetherto/wdk';
import WalletManagerEvm from '@tetherto/wdk-wallet-evm';

// ─────────────────────────────────────────────────────────────────────────────
// Config
// ─────────────────────────────────────────────────────────────────────────────

const PORT       = parseInt(process.env.WDK_SERVICE_PORT || '3001', 10);
const CHAIN      = process.env.WDK_CHAIN || 'polygon';
const RPC_URL    = process.env.WDK_RPC_URL || 'https://polygon-rpc.com';
const API_KEY    = process.env.WDK_API_KEY || '';
const SEED       = process.env.WDK_SEED_PHRASE || '';

const USDT_CONTRACTS = {
  polygon:  '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
  ethereum: '0xdAC17F958D2ee523a2206206994597C13D831ec7',
};
const USDT_DECIMALS = 6;

// Minimal ERC-20 ABI — only what we need
const ERC20_ABI = [
  'function transfer(address to, uint256 amount) returns (bool)',
  'function balanceOf(address owner) view returns (uint256)',
];

// ─────────────────────────────────────────────────────────────────────────────
// WDK initialisation
// ─────────────────────────────────────────────────────────────────────────────

let account;         // WDK account object
let provider;        // ethers.js JsonRpcProvider for read operations
let usdtContract;    // ethers.js Contract for USDT balance reads

async function initWDK() {
  if (!SEED) {
    throw new Error(
      'WDK_SEED_PHRASE is not set. Add a 12-word mnemonic to your .env file.'
    );
  }

  console.log(`[WDK] Initialising wallet on ${CHAIN} via ${RPC_URL}...`);

  const wdk = new WDK(SEED).registerWallet(CHAIN, WalletManagerEvm, {
    rpcUrl: RPC_URL,
  });

  account = await wdk.getAccount(CHAIN, 0);

  provider     = new ethers.JsonRpcProvider(RPC_URL);
  usdtContract = new ethers.Contract(
    USDT_CONTRACTS[CHAIN] || USDT_CONTRACTS.polygon,
    ERC20_ABI,
    provider
  );

  console.log(`[WDK] Ready. Address: ${account.address}`);
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function toUsdtUnits(amount) {
  // amount is a float in USD; USDT is 1:1 USD, 6 decimals
  return ethers.parseUnits(amount.toFixed(USDT_DECIMALS), USDT_DECIMALS);
}

async function getUsdtBalance(address) {
  const raw = await usdtContract.balanceOf(address);
  return parseFloat(ethers.formatUnits(raw, USDT_DECIMALS));
}

// Encode an ERC-20 transfer call to pass to WDK's sendTransaction
function encodeUsdtTransfer(to, amountFloat) {
  const iface = new ethers.Interface(ERC20_ABI);
  return iface.encodeFunctionData('transfer', [to, toUsdtUnits(amountFloat)]);
}

// ─────────────────────────────────────────────────────────────────────────────
// Express app
// ─────────────────────────────────────────────────────────────────────────────

const app = express();
app.use(express.json());

// Auth middleware — validates WDK_API_KEY bearer token if set
app.use((req, res, next) => {
  if (!API_KEY) return next();   // no auth configured → allow all
  const auth = req.headers['authorization'] || '';
  if (auth !== `Bearer ${API_KEY}`) {
    return res.status(401).json({ error: 'Unauthorised' });
  }
  next();
});

// Guard: reject requests before WDK is ready
app.use((req, res, next) => {
  if (req.path === '/health') return next();
  if (!account) return res.status(503).json({ error: 'WDK not ready yet' });
  next();
});

// ── GET /health ─────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({
    status: account ? 'ready' : 'initialising',
    address: account?.address ?? null,
    chain: CHAIN,
    rpc: RPC_URL,
  });
});

// ── GET /address ─────────────────────────────────────────────────────────────
app.get('/address', (_req, res) => {
  res.json({ address: account.address });
});

// ── GET /balance ─────────────────────────────────────────────────────────────
app.get('/balance', async (req, res) => {
  try {
    const token = (req.query.token || 'USDT').toUpperCase();
    let balance;

    if (token === 'USDT') {
      balance = await getUsdtBalance(account.address);
    } else {
      // Native token (MATIC / ETH)
      const raw = await provider.getBalance(account.address);
      balance = parseFloat(ethers.formatEther(raw));
    }

    res.json({ balance, token, address: account.address });
  } catch (err) {
    console.error('[WDK] /balance error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── POST /send ────────────────────────────────────────────────────────────────
app.post('/send', async (req, res) => {
  const { to, amount, token = 'USDT' } = req.body;

  if (!to || !amount) {
    return res.status(400).json({ error: 'Missing required fields: to, amount' });
  }
  if (!ethers.isAddress(to)) {
    return res.status(400).json({ error: `Invalid address: ${to}` });
  }

  try {
    const usdtAddr = USDT_CONTRACTS[CHAIN];
    console.log(`[WDK] Sending ${amount} ${token} → ${to}`);

    // Build the ERC-20 transfer transaction
    const tx = {
      to:    usdtAddr,
      data:  encodeUsdtTransfer(to, amount),
      value: '0',
    };

    // WDK signs and broadcasts the transaction
    const { hash: txHash, fee: txFee } = await account.sendTransaction(tx);

    console.log(`[WDK] Broadcast ✓ tx_hash=${txHash}  fee=${txFee}`);

    res.json({
      tx_hash: txHash,
      fee:     txFee?.toString() ?? '0',
      from:    account.address,
      to,
      amount,
      token,
      status:  'confirmed',
    });
  } catch (err) {
    console.error('[WDK] /send error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── GET /tx/:hash ─────────────────────────────────────────────────────────────
app.get('/tx/:hash', async (req, res) => {
  try {
    const receipt = await provider.getTransactionReceipt(req.params.hash);
    if (!receipt) {
      return res.json({ hash: req.params.hash, status: 'pending' });
    }
    res.json({
      hash:   req.params.hash,
      status: receipt.status === 1 ? 'confirmed' : 'failed',
      block:  receipt.blockNumber,
      gas:    receipt.gasUsed?.toString(),
    });
  } catch (err) {
    console.error('[WDK] /tx error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────────────

app.listen(PORT, async () => {
  console.log(`[WDK] Service listening on http://localhost:${PORT}`);
  try {
    await initWDK();
  } catch (err) {
    console.error(`[WDK] Initialisation failed: ${err.message}`);
    console.error('[WDK] Set WDK_SEED_PHRASE in .env to enable live transactions.');
    // Keep the server running so /health reports the error state
  }
});
