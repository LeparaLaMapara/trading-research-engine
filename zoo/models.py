"""The zoo. Every model maps (panel, train rows, test rows) -> raw forecast for the test rows.

Rules take no training. Learned models fit on the train rows only. Scaling to mean |f| = 1
happens in the driver, from TRAINING rows, identically for every model.

One fixed canonical configuration per model. No hyperparameter search: every configuration
tried would be another trial in N, and a searched optimum is exactly what deflation punishes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from zoo.panel import BREAKOUT, EWMAC, FEATURES

SEED = 7
LINEAR_FEATURES = [f for f in FEATURES if f != "class_id"]


# ---------------------------------------------------------------- baselines and rules

def cash(p, tr, te):
    return np.zeros(te.sum())


def long_risk_parity(p, tr, te):
    return np.ones(te.sum())


def random_sign(p, tr, te):
    """A coin flip per instrument per 20-day block. Held for the block so its cost is fair."""
    sub = p.loc[te, ["symbol", "date"]]
    block = (sub["date"].astype("int64") // (20 * 86400 * 10**9)).astype(np.int64)
    key = pd.util.hash_pandas_object(sub["symbol"] + block.astype(str), index=False)
    return np.where((key.to_numpy() + SEED) % 2 == 0, 1.0, -1.0)


def ewmac(p, tr, te):
    cols = [f"ewmac_{f}_{s}" for f, s in EWMAC]
    x = p.loc[:, cols]
    scale = x.loc[tr].abs().mean()           # each speed normalised on training data only
    return (x.loc[te] / scale).mean(axis=1).to_numpy()


def breakout(p, tr, te):
    return p.loc[te, [f"brk_{n}" for n in BREAKOUT]].mean(axis=1).to_numpy()


def tsmom_12m(p, tr, te):
    return np.sign(p.loc[te, "mom_250"].to_numpy())


def xs_momentum(p, tr, te):
    return p.loc[te, "xs_rank120"].to_numpy()


def short_reversal(p, tr, te):
    return -p.loc[te, "mom_5"].to_numpy()


# ---------------------------------------------------------------- learned models

def _train_xy(p, tr, cols, fill=True):
    rows = tr & p["y_5"].notna()
    X = p.loc[rows, cols]
    return rows, X, p.loc[rows, "y_5"].to_numpy()


def _standardise(p, tr, te, cols):
    mu = p.loc[tr, cols].mean()
    sd = p.loc[tr, cols].std().replace(0, 1.0)
    z = lambda m: ((p.loc[m, cols] - mu) / sd).clip(-5, 5).fillna(0.0).to_numpy(np.float32)
    return z, mu, sd


def ridge_pooled(p, tr, te, alpha=10.0):
    from sklearn.linear_model import Ridge
    rows = tr & p["y_5"].notna()
    z, _, _ = _standardise(p, rows, te, LINEAR_FEATURES)
    m = Ridge(alpha=alpha).fit(z(rows), p.loc[rows, "y_5"].to_numpy())
    return m.predict(z(te)), m.predict(z(rows))


def logistic_pooled(p, tr, te):
    from sklearn.linear_model import LogisticRegression
    rows = tr & p["y_5"].notna()
    z, _, _ = _standardise(p, rows, te, LINEAR_FEATURES)
    y = (p.loc[rows, "y_5"] > 0).astype(int).to_numpy()
    m = LogisticRegression(C=0.1, max_iter=500).fit(z(rows), y)
    return m.predict_proba(z(te))[:, 1] - 0.5, m.predict_proba(z(rows))[:, 1] - 0.5


def _ridge_grouped(p, tr, te, key):
    out = np.zeros(te.sum())
    ins = []
    te_keys = p.loc[te, key].to_numpy()
    for k in np.unique(te_keys):
        g_tr = tr & (p[key] == k)
        g_te = te & (p[key] == k)
        if (g_tr & p["y_5"].notna()).sum() < 500:
            continue                           # too little history: forecast stays 0
        pred, fit = ridge_pooled(p, g_tr, g_te)
        out[te_keys == k] = pred
        ins.append(fit)
    return out, (np.concatenate(ins) if ins else np.zeros(1))


def ridge_per_class(p, tr, te):
    return _ridge_grouped(p, tr, te, "asset_class")


def ridge_per_instrument(p, tr, te):
    return _ridge_grouped(p, tr, te, "symbol")


def _xgb(p, tr, te, depth):
    import xgboost as xgb
    rows = tr & p["y_5"].notna()
    kw = dict(n_estimators=300, max_depth=depth, learning_rate=0.03, subsample=0.7,
              colsample_bytree=0.7, min_child_weight=200, reg_lambda=10.0, random_state=SEED,
              tree_method="hist")
    try:
        m = xgb.XGBRegressor(device="cuda", **kw)
        m.fit(p.loc[rows, FEATURES], p.loc[rows, "y_5"])
    except Exception:                          # noqa: BLE001  no GPU: same model on CPU
        m = xgb.XGBRegressor(**kw)
        m.fit(p.loc[rows, FEATURES], p.loc[rows, "y_5"])
    return m.predict(p.loc[te, FEATURES]), m.predict(p.loc[rows, FEATURES])


def xgb_shallow(p, tr, te):
    return _xgb(p, tr, te, 3)


def xgb_deep(p, tr, te):
    return _xgb(p, tr, te, 6)


def _forest(p, tr, te, cls):
    rows = tr & p["y_5"].notna()
    X = p.loc[rows, FEATURES].fillna(0.0).to_numpy(np.float32)
    m = cls(n_estimators=200, min_samples_leaf=200, max_features=0.5, n_jobs=-1,
            random_state=SEED).fit(X, p.loc[rows, "y_5"].to_numpy())
    Xt = p.loc[te, FEATURES].fillna(0.0).to_numpy(np.float32)
    return m.predict(Xt), m.predict(X[:: 5])


def extra_trees(p, tr, te):
    from sklearn.ensemble import ExtraTreesRegressor
    return _forest(p, tr, te, ExtraTreesRegressor)


def random_forest(p, tr, te):
    from sklearn.ensemble import RandomForestRegressor
    return _forest(p, tr, te, RandomForestRegressor)


def _torch_fit(Xtr, ytr, Xte, net, epochs, lr=1e-3, wd=1e-4, batch=2048):
    import torch
    torch.manual_seed(SEED)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = net.to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=wd)
    lossf = torch.nn.HuberLoss()
    Xt = torch.tensor(Xtr, device=dev)
    yt = torch.tensor(ytr, dtype=torch.float32, device=dev)
    g = torch.Generator(device="cpu").manual_seed(SEED)
    for _ in range(epochs):
        net.train()
        perm = torch.randperm(len(Xt), generator=g).to(dev)
        for i in range(0, len(Xt), batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            loss = lossf(net(Xt[idx]).squeeze(-1), yt[idx])
            loss.backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        pred = lambda X: torch.cat([net(torch.tensor(X[i:i + 8192], device=dev)).squeeze(-1)
                                    for i in range(0, len(X), 8192)]).cpu().numpy()
        return pred(Xte), pred(Xtr[:: 5])


def mlp(p, tr, te):
    import torch.nn as nn
    rows = tr & p["y_5"].notna()
    z, _, _ = _standardise(p, rows, te, LINEAR_FEATURES)
    net = nn.Sequential(nn.Linear(len(LINEAR_FEATURES), 64), nn.ReLU(), nn.Dropout(0.2),
                        nn.Linear(64, 32), nn.ReLU(), nn.Dropout(0.2), nn.Linear(32, 1))
    return _torch_fit(z(rows), p.loc[rows, "y_5"].to_numpy(), z(te), net, epochs=15)


SEQ_LEN = 60


def sequences(p: pd.DataFrame) -> np.ndarray:
    """For every panel row, the previous SEQ_LEN vol-normalised daily returns of that
    instrument ending at the row's own date. Built once; rows are in panel order."""
    out = np.zeros((len(p), SEQ_LEN, 1), dtype=np.float32)
    z = (p["ret"] / p["sigma"].groupby(p["symbol"]).shift(1)).clip(-6, 6).fillna(0.0)
    for _, idx in p.groupby("symbol").indices.items():
        idx = np.sort(idx)
        order = p["date"].to_numpy()[idx].argsort(kind="stable")
        idx = idx[order]
        v = z.to_numpy()[idx].astype(np.float32)
        pad = np.concatenate([np.zeros(SEQ_LEN - 1, np.float32), v])
        win = np.lib.stride_tricks.sliding_window_view(pad, SEQ_LEN)
        out[idx, :, 0] = win
    return out


class _GRU:
    def __new__(cls):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.gru = nn.GRU(1, 32, batch_first=True)
                self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(32, 1))

            def forward(self, x):
                h, _ = self.gru(x)
                return self.head(h[:, -1, :])
        return Net()


def gru_seq(p, tr, te, seq=None):
    rows = (tr & p["y_5"].notna()).to_numpy()
    S = seq if seq is not None else sequences(p)
    return _torch_fit(S[rows], p.loc[rows, "y_5"].to_numpy(), S[te.to_numpy()], _GRU(),
                      epochs=8)


RULES = {"ewmac": ewmac, "breakout": breakout, "tsmom_12m": tsmom_12m,
         "xs_momentum": xs_momentum, "short_reversal": short_reversal}
BASELINES = {"cash": cash, "long_risk_parity": long_risk_parity, "random_sign": random_sign}
LEARNED = {"ridge_pooled": ridge_pooled, "logistic_pooled": logistic_pooled,
           "ridge_per_class": ridge_per_class, "ridge_per_instrument": ridge_per_instrument,
           "xgb_shallow": xgb_shallow, "xgb_deep": xgb_deep, "extra_trees": extra_trees,
           "random_forest": random_forest, "mlp": mlp, "gru_seq": gru_seq}
ENSEMBLES = {"ens_rules": list(RULES), "ens_ml": list(LEARNED),
             "ens_all": list(RULES) + list(LEARNED)}
