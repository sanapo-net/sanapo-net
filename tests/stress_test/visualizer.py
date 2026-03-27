# tests/stress_test/mock_module.py
import pandas as pd
import matplotlib.pyplot as plt

import os

import tests.stress_test.params as params

def analyze_and_plot(all_data):
    path = "tests/stress_test/results"
    os.makedirs(path, exist_ok=True)
    summary = {}

    for idx, logs in enumerate(all_data):
        df = pd.DataFrame(logs)
        sent = df[df['sent_time'].notnull()].copy()
        recv = df[df['received_time'].notnull()].copy()
        merged = pd.merge(sent, recv[['payload', 'recipient', 'received_time']], on='payload')
        merged['delay'] = (merged['received_time'] - merged['sent_time']) * 1000
        summary[idx] = (merged, sent)

        # Рендерим матрицы итерации
        _render(merged, sent, params.MODULE_NAMES + ["BUFFER"], f"Evt_{idx}", f"{path}/evt_{idx+1}.png")
        _render(merged, sent, params.MODULE_NAMES, f"Cmd_{idx}", f"{path}/cmd_{idx+1}.png")

    _render_summary(summary, params.MODULE_NAMES + ["BUFFER"], f"{path}/summary_final.png")

def _render(merged, sent, addrs, title, out):
    n = len(addrs)
    fig, axes = plt.subplots(n, n, figsize=(n*2, n*2), constrained_layout=True)
    for i, s in enumerate(addrs):
        for j, r in enumerate(addrs):
            ax = axes[i, j]
            if s == r: continue
            data = merged[(merged['sender'] == s) & (merged['recipient'] == r)]['delay']
            lost = len(sent[sent['sender'] == s]) - len(data)
            if not data.empty:
                ax.hist(data, bins=15, color='skyblue', range=(0, 100))
                ax.text(0.9, 0.9, f"M:{data.median():.1f}", transform=ax.transAxes, color='blue', ha='right', fontsize=8)
            if lost > 0:
                ax.text(0.1, 0.9, f"L:{lost}", transform=ax.transAxes, color='red', fontsize=9, fontweight='bold')
    plt.savefig(out, dpi=120); plt.close()

def _render_summary(summary, addrs, out):
    n = len(addrs)
    fig, axes = plt.subplots(n, n, figsize=(n*2, n*2), constrained_layout=True)
    for i, s in enumerate(addrs):
        for j, r in enumerate(addrs):
            ax = axes[i, j]
            if s == r: continue
            m_v, l_v = [], []
            for it in range(8):
                m_df, s_df = summary[it]
                p = m_df[(m_df['sender'] == s) & (m_df['recipient'] == r)]['delay']
                m_v.append(p.median() if not p.empty else 0)
                l_v.append(len(s_df[s_df['sender'] == s]) - len(p))
            ax.plot(range(1, 9), m_v, 'b-'); ax.tick_params(labelsize=6)
            ax_l = ax.twinx(); ax_l.plot(range(1, 9), l_v, 'r--'); ax_l.tick_params(labelsize=6)
    plt.savefig(out, dpi=150); plt.close()
