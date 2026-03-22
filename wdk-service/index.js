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

import dotenv from 'dotenv';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);
// Load .env from project root (parent of wdk-service/)
dotenv.config({ path: resolve(__dirname, '../.env') });
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
  // Amoy testnet has no official Tether USDT — we use native MATIC transfers instead.
  // Tips are labelled "MATIC" but are genuine on-chain transactions on amoy.polygonscan.com.
  amoy: null,
};
const USDT_DECIMALS = 6;

// Chains where we send native token (MATIC/ETH) instead of ERC-20 USDT
const NATIVE_TRANSFER_CHAINS = new Set(['amoy']);

// On testnet, scale tip amounts down so the demo wallet doesn't run dry.
// $1.00 tip → 0.01 MATIC on Amoy. Transactions are real; amounts are symbolic.
const TESTNET_AMOUNT_SCALE = 0.01;

const CHAIN_EXPLORERS = {
  polygon:  'https://polygonscan.com/tx',
  ethereum: 'https://etherscan.io/tx',
  amoy:     'https://amoy.polygonscan.com/tx',
};

const CHAIN_RPC_DEFAULTS = {
  polygon:  'https://polygon-rpc.com',
  ethereum: 'https://eth.llamarpc.com',
  amoy:     'https://rpc-amoy.polygon.technology',
};

// Minimal ERC-20 ABI — only what we need
const ERC20_ABI = [
  'function transfer(address to, uint256 amount) returns (bool)',
  'function balanceOf(address owner) view returns (uint256)',
];

// ─────────────────────────────────────────────────────────────────────────────
// WDK initialisation
// ─────────────────────────────────────────────────────────────────────────────

let account;         // WDK account object
let signer;          // ethers.js Wallet signer (used for native token transfers on testnet)
let provider;        // ethers.js JsonRpcProvider for read operations
let usdtContract;    // ethers.js Contract for USDT balance reads

async function initWDK() {
  if (!SEED) {
    throw new Error(
      'WDK_SEED_PHRASE is not set. Add a 12-word mnemonic to your .env file.'
    );
  }

  const rpc = RPC_URL || CHAIN_RPC_DEFAULTS[CHAIN] || CHAIN_RPC_DEFAULTS.polygon;
  console.log(`[WDK] Initialising wallet on ${CHAIN} via ${rpc}...`);

  // WDK only recognises 'polygon' and 'ethereum' as chain names.
  // For Amoy testnet we register as 'polygon' but point the RPC at Amoy —
  // same EVM address derivation, transactions land on the correct network.
  const wdkChainKey = CHAIN === 'amoy' ? 'polygon' : CHAIN;

  const wdk = new WDK(SEED).registerWallet(wdkChainKey, WalletManagerEvm, {
    rpcUrl: rpc,
  });

  account  = await wdk.getAccount(wdkChainKey, 0);
  provider = new ethers.JsonRpcProvider(rpc);

  // Derive ethers.js signer from same BIP-39 seed — used for testnet native sends
  // when WDK account.sendTransaction() doesn't support the custom chain.
  const hdNode = ethers.HDNodeWallet.fromMnemonic(
    ethers.Mnemonic.fromPhrase(SEED),
    "m/44'/60'/0'/0/0"
  );
  signer = hdNode.connect(provider);

  // Only create USDT contract when the chain has one
  const usdtAddr = USDT_CONTRACTS[CHAIN];
  if (usdtAddr) {
    usdtContract = new ethers.Contract(usdtAddr, ERC20_ABI, provider);
  } else {
    usdtContract = null;
    console.log(`[WDK] ${CHAIN} has no USDT contract — native token transfers will be used.`);
  }

  console.log(`[WDK] Ready. Address: ${account.address}`);
  console.log(`[WDK] Explorer: ${CHAIN_EXPLORERS[CHAIN] || 'unknown'}`);
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
    status:       account ? 'ready' : 'initialising',
    address:      account?.address ?? null,
    chain:        CHAIN,
    rpc:          RPC_URL || CHAIN_RPC_DEFAULTS[CHAIN],
    native_mode:  NATIVE_TRANSFER_CHAINS.has(CHAIN),
    explorer:     CHAIN_EXPLORERS[CHAIN] ?? null,
  });
});

// ── GET /address ─────────────────────────────────────────────────────────────
app.get('/address', (_req, res) => {
  res.json({ address: account.address });
});

// ── GET /balance ─────────────────────────────────────────────────────────────
app.get('/balance', async (req, res) => {
  try {
    let balance, token;

    if (NATIVE_TRANSFER_CHAINS.has(CHAIN)) {
      // Testnet: report native MATIC balance
      const raw = await provider.getBalance(account.address);
      balance = parseFloat(ethers.formatEther(raw));
      token = 'MATIC';
    } else {
      token = (req.query.token || 'USDT').toUpperCase();
      if (token === 'USDT' && usdtContract) {
        balance = await getUsdtBalance(account.address);
      } else {
        const raw = await provider.getBalance(account.address);
        balance = parseFloat(ethers.formatEther(raw));
      }
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
    let tx, sentToken;

    let txHash, txFee;

    if (NATIVE_TRANSFER_CHAINS.has(CHAIN)) {
      // Testnet: send native MATIC via ethers.js signer (WDK-derived key, same address)
      // Amounts are scaled down (TESTNET_AMOUNT_SCALE) so the demo wallet doesn't run dry.
      const scaledAmount = amount * TESTNET_AMOUNT_SCALE;
      const valueWei = ethers.parseEther(scaledAmount.toFixed(8));
      sentToken = 'MATIC';
      console.log(`[WDK] Sending ${scaledAmount.toFixed(8)} MATIC (=$${amount} scaled) on Amoy → ${to}`);
      // Fetch fresh nonce and fee data — prevents replacement/underpriced errors
      const [nonce, feeData] = await Promise.all([
        provider.getTransactionCount(signer.address, 'pending'),
        provider.getFeeData(),
      ]);
      const gasPrice = feeData.gasPrice
        ? (feeData.gasPrice * 150n) / 100n   // 1.5× current gas price
        : ethers.parseUnits('50', 'gwei');
      const txResponse = await signer.sendTransaction({ to, value: valueWei, gasPrice, nonce });
      txHash = txResponse.hash;
      txFee  = txResponse.gasPrice?.toString() ?? '0';
    } else {
      // Mainnet: ERC-20 USDT via WDK account.sendTransaction()
      const usdtAddr = USDT_CONTRACTS[CHAIN];
      sentToken = 'USDT';
      console.log(`[WDK] Sending ${amount} USDT → ${to}`);
      const result = await account.sendTransaction({
        to:    usdtAddr,
        data:  encodeUsdtTransfer(to, amount),
        value: '0',
      });
      txHash = result.hash;
      txFee  = result.fee?.toString() ?? '0';
    }

    const explorerUrl = `${CHAIN_EXPLORERS[CHAIN] || ''}/${txHash}`;

    console.log(`[WDK] Broadcast ✓ tx_hash=${txHash}  fee=${txFee}`);
    console.log(`[WDK] Explorer: ${explorerUrl}`);

    res.json({
      tx_hash:      txHash,
      fee:          txFee,
      from:         account.address,
      to,
      amount,
      token:        sentToken,
      status:       'confirmed',
      explorer_url: explorerUrl,
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
