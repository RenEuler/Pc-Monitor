"""
PC Monitor - monitor de sistema em tempo real
---------------------------------------------
Monitora CPU (total e por nucleo), RAM/Swap, armazenamento, rede,
I/O de disco e processos (com ordenacao, filtro e finalizacao).

BY: Alves Renan
"""

import platform
import time
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

import psutil

# ----------------------------------------------------------------------------
# Configuracoes
# ----------------------------------------------------------------------------
INTERVALO_MS = 1000      # atualizacao da interface
HISTORICO = 60           # pontos no grafico (segundos)
MAX_PROCESSOS = 500      # limite de linhas na tabela de processos

# Paleta (tema escuro)
BG = "#0f172a"
CARD = "#1e293b"
CARD_ALT = "#152033"
GRADE = "#2b3a52"
TEXTO = "#e2e8f0"
TEXTO2 = "#94a3b8"
AZUL = "#38bdf8"
ROXO = "#a78bfa"
VERDE = "#22c55e"
AMARELO = "#eab308"
VERMELHO = "#ef4444"

FONTE = ("Segoe UI", 10)
FONTE_TITULO = ("Segoe UI", 10, "bold")
FONTE_GRANDE = ("Segoe UI", 26, "bold")


# ----------------------------------------------------------------------------
# Funcoes auxiliares
# ----------------------------------------------------------------------------
def fmt_bytes(n: float) -> str:
    """Converte bytes em uma string legivel (KB, MB, GB...)."""
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)} B" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_tempo(segundos: float) -> str:
    segundos = int(segundos)
    d, resto = divmod(segundos, 86400)
    h, resto = divmod(resto, 3600)
    m, s = divmod(resto, 60)
    return f"{d}d {h:02d}h {m:02d}m {s:02d}s" if d else f"{h:02d}h {m:02d}m {s:02d}s"


def nivel(pct: float) -> str:
    """Retorna o nome do estilo conforme o nivel de uso."""
    if pct < 60:
        return "Ok"
    if pct < 85:
        return "Warn"
    return "Crit"


COR_NIVEL = {"Ok": VERDE, "Warn": AMARELO, "Crit": VERMELHO}


def misturar(cor: str, fundo: str, t: float) -> str:
    """Mistura duas cores hex (simula transparencia, que o Tk nao possui)."""
    c = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    f = [int(fundo[i:i + 2], 16) for i in (1, 3, 5)]
    r = [round(f[i] + (c[i] - f[i]) * t) for i in range(3)]
    return "#{:02x}{:02x}{:02x}".format(*r)


# ----------------------------------------------------------------------------
# Widget de grafico de linha
# ----------------------------------------------------------------------------
class GraficoLinha(tk.Canvas):
    """Grafico simples (0-100%) desenhado num Canvas."""

    def __init__(self, master, cor: str, altura: int = 100, **kw):
        super().__init__(master, height=altura, bg=CARD_ALT,
                         highlightthickness=0, **kw)
        self.cor = cor
        self.cor_fill = misturar(cor, CARD_ALT, 0.28)
        self.dados: list[float] = []
        self.bind("<Configure>", lambda _e: self.desenhar())

    def atualizar(self, dados):
        self.dados = list(dados)
        self.desenhar()

    def desenhar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        for i in range(1, 4):                      # linhas de grade
            y = h * i / 4
            self.create_line(0, y, w, y, fill=GRADE)
        n = len(self.dados)
        if n < 2:
            return
        passo = w / (n - 1)
        pontos = []
        for i, v in enumerate(self.dados):
            pontos += [i * passo, h - 2 - (max(0, min(v, 100)) / 100) * (h - 4)]
        self.create_polygon([0, h] + pontos + [w, h], fill=self.cor_fill, outline="")
        self.create_line(*pontos, fill=self.cor, width=2)


# ----------------------------------------------------------------------------
# Aplicacao principal
# ----------------------------------------------------------------------------
class PCMonitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PC Monitor")
        self.geometry("1000x700")
        self.minsize(880, 620)
        self.configure(bg=BG)

        self.hist_cpu = deque([0.0] * HISTORICO, maxlen=HISTORICO)
        self.hist_ram = deque([0.0] * HISTORICO, maxlen=HISTORICO)
        self.tick = 0
        self.ordem_col = "cpu"
        self.ordem_desc = True

        # Contadores anteriores para calcular velocidades (rede / disco)
        self.ult_tempo = time.time()
        self.ult_rede = psutil.net_io_counters()
        self.ult_disco = psutil.disk_io_counters()

        # "Aquece" os medidores de CPU (a primeira leitura sempre retorna 0)
        psutil.cpu_percent(None)
        psutil.cpu_percent(None, percpu=True)

        self._configurar_estilos()
        self._criar_cabecalho()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.aba_geral = tk.Frame(self.nb, bg=BG)
        self.aba_disco = tk.Frame(self.nb, bg=BG)
        self.aba_proc = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.aba_geral, text="  Visão geral  ")
        self.nb.add(self.aba_disco, text="  Armazenamento  ")
        self.nb.add(self.aba_proc, text="  Processos  ")
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._atualizar_aba_atual(True))

        self._criar_aba_geral()
        self._criar_aba_disco()
        self._criar_aba_processos()

        self._atualizar()

    # ------------------------------------------------------------------ estilos
    def _configurar_estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=CARD, foreground=TEXTO2,
                    padding=(14, 7), borderwidth=0, font=FONTE_TITULO)
        s.map("TNotebook.Tab",
              background=[("selected", AZUL)],
              foreground=[("selected", BG)])

        for nome, cor in COR_NIVEL.items():
            s.configure(f"{nome}.Horizontal.TProgressbar", troughcolor=CARD_ALT,
                        background=cor, lightcolor=cor, darkcolor=cor,
                        bordercolor=CARD, thickness=14)

        s.configure("Treeview", background=CARD, fieldbackground=CARD,
                    foreground=TEXTO, rowheight=24, borderwidth=0, font=FONTE)
        s.configure("Treeview.Heading", background=CARD_ALT, foreground=AZUL,
                    relief="flat", font=FONTE_TITULO, padding=6)
        s.map("Treeview",
              background=[("selected", "#334155")],
              foreground=[("selected", "#ffffff")])
        s.map("Treeview.Heading", background=[("active", GRADE)])
        s.configure("Vertical.TScrollbar", background=GRADE, troughcolor=CARD,
                    bordercolor=CARD, arrowcolor=TEXTO2)

    # ---------------------------------------------------------------- cabecalho
    def _criar_cabecalho(self):
        f = tk.Frame(self, bg=BG)
        f.pack(fill="x", padx=16, pady=(14, 10))

        tk.Label(f, text="🖥  PC Monitor", bg=BG, fg=TEXTO,
                 font=("Segoe UI", 18, "bold")).pack(side="left")

        info = (f"{platform.node()}  •  {platform.system()} {platform.release()}  •  "
                f"{psutil.cpu_count(logical=False) or '?'} núcleos físicos / "
                f"{psutil.cpu_count()} lógicos")
        tk.Label(f, text=info, bg=BG, fg=TEXTO2, font=FONTE).pack(side="left", padx=16)

        self.lbl_uptime = tk.Label(f, text="", bg=BG, fg=TEXTO2, font=FONTE)
        self.lbl_uptime.pack(side="right")

    # ---------------------------------------------------------------- aba geral
    def _card(self, master, titulo, **grid):
        f = tk.Frame(master, bg=CARD, padx=16, pady=12)
        f.grid(**grid)
        tk.Label(f, text=titulo, bg=CARD, fg=TEXTO2, font=FONTE_TITULO).pack(anchor="w")
        return f

    def _criar_aba_geral(self):
        g = self.aba_geral
        g.columnconfigure(0, weight=1, uniform="col")
        g.columnconfigure(1, weight=1, uniform="col")

        # --- CPU
        cpu = self._card(g, "CPU", row=0, column=0, sticky="nsew", padx=(0, 6), pady=(8, 6))
        self.lbl_cpu = tk.Label(cpu, text="0%", bg=CARD, fg=AZUL, font=FONTE_GRANDE)
        self.lbl_cpu.pack(anchor="w")
        self.lbl_cpu_info = tk.Label(cpu, text="", bg=CARD, fg=TEXTO2, font=FONTE)
        self.lbl_cpu_info.pack(anchor="w", pady=(0, 6))
        self.bar_cpu = ttk.Progressbar(cpu, maximum=100, style="Ok.Horizontal.TProgressbar")
        self.bar_cpu.pack(fill="x", pady=(0, 8))
        self.graf_cpu = GraficoLinha(cpu, AZUL)
        self.graf_cpu.pack(fill="x")

        # --- RAM
        ram = self._card(g, "Memória RAM", row=0, column=1, sticky="nsew", padx=(6, 0), pady=(8, 6))
        self.lbl_ram = tk.Label(ram, text="0%", bg=CARD, fg=ROXO, font=FONTE_GRANDE)
        self.lbl_ram.pack(anchor="w")
        self.lbl_ram_info = tk.Label(ram, text="", bg=CARD, fg=TEXTO2, font=FONTE)
        self.lbl_ram_info.pack(anchor="w", pady=(0, 6))
        self.bar_ram = ttk.Progressbar(ram, maximum=100, style="Ok.Horizontal.TProgressbar")
        self.bar_ram.pack(fill="x", pady=(0, 8))
        self.graf_ram = GraficoLinha(ram, ROXO)
        self.graf_ram.pack(fill="x")
        self.lbl_swap = tk.Label(ram, text="", bg=CARD, fg=TEXTO2, font=FONTE)
        self.lbl_swap.pack(anchor="w", pady=(6, 0))

        # --- Nucleos
        nuc = self._card(g, "Uso por núcleo", row=1, column=0, columnspan=2,
                         sticky="nsew", pady=6)
        grade = tk.Frame(nuc, bg=CARD)
        grade.pack(fill="x", pady=(6, 0))
        self.nucleos = []
        total = psutil.cpu_count() or 1
        colunas = 4
        for c in range(colunas):
            grade.columnconfigure(c, weight=1, uniform="nuc")
        for i in range(total):
            cel = tk.Frame(grade, bg=CARD)
            cel.grid(row=i // colunas, column=i % colunas, sticky="ew", padx=6, pady=3)
            lbl = tk.Label(cel, text=f"Núcleo {i}", bg=CARD, fg=TEXTO2, font=("Segoe UI", 9))
            lbl.pack(anchor="w")
            bar = ttk.Progressbar(cel, maximum=100, style="Ok.Horizontal.TProgressbar")
            bar.pack(fill="x")
            self.nucleos.append((lbl, bar))

        # --- Rede / disco
        io = self._card(g, "Rede e disco (tempo real)", row=2, column=0, columnspan=2,
                        sticky="nsew", pady=(6, 0))
        linha = tk.Frame(io, bg=CARD)
        linha.pack(fill="x", pady=(6, 0))
        self.lbl_rede = tk.Label(linha, text="", bg=CARD, fg=TEXTO, font=FONTE)
        self.lbl_rede.pack(side="left")
        self.lbl_disco_io = tk.Label(linha, text="", bg=CARD, fg=TEXTO, font=FONTE)
        self.lbl_disco_io.pack(side="right")

    # ------------------------------------------------------------- aba armazenamento
    def _criar_aba_disco(self):
        cols = ("dev", "mnt", "fs", "total", "usado", "livre", "pct")
        titulos = ("Dispositivo", "Ponto de montagem", "Sistema", "Total",
                   "Usado", "Livre", "Uso %")
        larguras = (170, 220, 90, 100, 100, 100, 80)

        f = tk.Frame(self.aba_disco, bg=BG)
        f.pack(fill="both", expand=True, pady=(8, 0))
        self.tree_disco = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for c, t, w in zip(cols, titulos, larguras):
            self.tree_disco.heading(c, text=t)
            self.tree_disco.column(c, width=w, anchor="w" if c in ("dev", "mnt", "fs") else "e")
        self.tree_disco.pack(fill="both", expand=True)
        self.tree_disco.tag_configure("warn", foreground=AMARELO)
        self.tree_disco.tag_configure("crit", foreground=VERMELHO)

    def _atualizar_disco(self):
        self.tree_disco.delete(*self.tree_disco.get_children())
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
            except (PermissionError, OSError):
                continue  # ex.: leitor de CD vazio no Windows
            tag = {"Ok": "", "Warn": "warn", "Crit": "crit"}[nivel(u.percent)]
            self.tree_disco.insert("", "end", tags=(tag,), values=(
                p.device, p.mountpoint, p.fstype or "-", fmt_bytes(u.total),
                fmt_bytes(u.used), fmt_bytes(u.free), f"{u.percent:.1f}%"))

    # ---------------------------------------------------------------- aba processos
    def _criar_aba_processos(self):
        topo = tk.Frame(self.aba_proc, bg=BG)
        topo.pack(fill="x", pady=(8, 8))

        tk.Label(topo, text="Filtrar:", bg=BG, fg=TEXTO2, font=FONTE).pack(side="left")
        self.var_filtro = tk.StringVar()
        ent = tk.Entry(topo, textvariable=self.var_filtro, bg=CARD, fg=TEXTO,
                       insertbackground=TEXTO, relief="flat", font=FONTE, width=28)
        ent.pack(side="left", padx=8, ipady=4)
        ent.bind("<KeyRelease>", lambda _e: self._atualizar_processos())

        self.lbl_total_proc = tk.Label(topo, text="", bg=BG, fg=TEXTO2, font=FONTE)
        self.lbl_total_proc.pack(side="left", padx=8)

        tk.Button(topo, text="Finalizar processo", command=self._finalizar_processo,
                  bg=VERMELHO, fg="white", activebackground="#b91c1c",
                  activeforeground="white", relief="flat", font=FONTE_TITULO,
                  padx=12, pady=4, cursor="hand2").pack(side="right")

        self.cols_proc = ("pid", "nome", "usuario", "cpu", "mem_pct", "rss", "status")
        self.titulos_proc = {"pid": "PID", "nome": "Nome", "usuario": "Usuário",
                             "cpu": "CPU %", "mem_pct": "Mem %", "rss": "Memória",
                             "status": "Status"}
        larguras = {"pid": 70, "nome": 260, "usuario": 150, "cpu": 80,
                    "mem_pct": 80, "rss": 110, "status": 100}

        f = tk.Frame(self.aba_proc, bg=BG)
        f.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(f, columns=self.cols_proc, show="headings", selectmode="browse")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        for c in self.cols_proc:
            self.tree.heading(c, text=self.titulos_proc[c], command=lambda k=c: self._ordenar(k))
            self.tree.column(c, width=larguras[c],
                             anchor="w" if c in ("nome", "usuario", "status") else "e")
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._marcar_cabecalho()

    def _ordenar(self, coluna):
        if coluna == self.ordem_col:
            self.ordem_desc = not self.ordem_desc
        else:
            self.ordem_col = coluna
            self.ordem_desc = coluna in ("cpu", "mem_pct", "rss")
        self._marcar_cabecalho()
        self._atualizar_processos()

    def _marcar_cabecalho(self):
        for c in self.cols_proc:
            seta = ""
            if c == self.ordem_col:
                seta = "  ▼" if self.ordem_desc else "  ▲"
            self.tree.heading(c, text=self.titulos_proc[c] + seta)

    def _atualizar_processos(self):
        filtro = self.var_filtro.get().strip().lower()
        n_cpu = psutil.cpu_count() or 1
        linhas = []
        attrs = ["pid", "name", "username", "cpu_percent", "memory_percent",
                 "memory_info", "status"]
        for p in psutil.process_iter(attrs):
            i = p.info
            nome = i.get("name") or "?"
            if filtro and filtro not in nome.lower() and filtro not in str(i["pid"]):
                continue
            mem = i.get("memory_info")
            linhas.append({
                "pid": i["pid"],
                "nome": nome,
                "usuario": (i.get("username") or "-").split("\\")[-1],
                "cpu": (i.get("cpu_percent") or 0.0) / n_cpu,   # normaliza p/ 0-100%
                "mem_pct": i.get("memory_percent") or 0.0,
                "rss": mem.rss if mem else 0,
                "status": i.get("status") or "-",
            })

        chave = self.ordem_col
        if chave in ("nome", "usuario", "status"):
            linhas.sort(key=lambda l: l[chave].lower(), reverse=self.ordem_desc)
        else:
            linhas.sort(key=lambda l: l[chave], reverse=self.ordem_desc)
        self.lbl_total_proc.config(text=f"{len(linhas)} processos")
        linhas = linhas[:MAX_PROCESSOS]

        # Atualiza a tabela "in place" para manter selecao e posicao do scroll
        existentes = set(self.tree.get_children())
        vistos = set()
        for idx, l in enumerate(linhas):
            iid = str(l["pid"])
            vistos.add(iid)
            valores = (l["pid"], l["nome"], l["usuario"], f"{l['cpu']:.1f}",
                       f"{l['mem_pct']:.1f}", fmt_bytes(l["rss"]), l["status"])
            if iid in existentes:
                self.tree.item(iid, values=valores)
                self.tree.move(iid, "", idx)
            else:
                self.tree.insert("", idx, iid=iid, values=valores)
        for iid in existentes - vistos:
            self.tree.delete(iid)

    def _finalizar_processo(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("PC Monitor", "Selecione um processo na lista.")
            return
        pid = int(sel[0])
        try:
            proc = psutil.Process(pid)
            nome = proc.name()
            if not messagebox.askyesno(
                    "Finalizar processo",
                    f"Deseja finalizar '{nome}' (PID {pid})?\n\n"
                    "Dados não salvos podem ser perdidos."):
                return
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()  # força o encerramento se não respondeu
        except psutil.NoSuchProcess:
            messagebox.showwarning("PC Monitor", "O processo já não existe mais.")
        except psutil.AccessDenied:
            messagebox.showerror("PC Monitor",
                                 "Acesso negado. Execute o programa como administrador.")
        self._atualizar_processos()

    # ------------------------------------------------------------- atualizacao
    def _atualizar_aba_atual(self, forcar=False):
        aba = self.nb.index(self.nb.select())
        if aba == 1 and (forcar or self.tick % 5 == 0):
            self._atualizar_disco()
        elif aba == 2 and (forcar or self.tick % 2 == 0):
            self._atualizar_processos()

    def _atualizar_visao_geral(self):
        # ---- CPU
        cpu = psutil.cpu_percent()
        por_nucleo = psutil.cpu_percent(percpu=True)
        self.hist_cpu.append(cpu)
        n = nivel(cpu)
        self.lbl_cpu.config(text=f"{cpu:.0f}%", fg=COR_NIVEL[n] if n != "Ok" else AZUL)
        self.bar_cpu.config(value=cpu, style=f"{n}.Horizontal.TProgressbar")
        self.graf_cpu.atualizar(self.hist_cpu)

        freq = psutil.cpu_freq()
        txt = f"{freq.current / 1000:.2f} GHz" if freq else "frequência indisponível"
        self.lbl_cpu_info.config(text=f"{txt}  •  {len(por_nucleo)} threads")

        for (lbl, bar), uso in zip(self.nucleos, por_nucleo):
            lbl.config(text=f"Núcleo {self.nucleos.index((lbl, bar))} — {uso:.0f}%")
            bar.config(value=uso, style=f"{nivel(uso)}.Horizontal.TProgressbar")

        # ---- RAM / swap
        mem = psutil.virtual_memory()
        self.hist_ram.append(mem.percent)
        n = nivel(mem.percent)
        self.lbl_ram.config(text=f"{mem.percent:.0f}%", fg=COR_NIVEL[n] if n != "Ok" else ROXO)
        self.bar_ram.config(value=mem.percent, style=f"{n}.Horizontal.TProgressbar")
        self.lbl_ram_info.config(
            text=f"{fmt_bytes(mem.used)} usados de {fmt_bytes(mem.total)}  •  "
                 f"{fmt_bytes(mem.available)} disponíveis")
        self.graf_ram.atualizar(self.hist_ram)
        swap = psutil.swap_memory()
        self.lbl_swap.config(
            text=f"Swap/arquivo de paginação: {fmt_bytes(swap.used)} de "
                 f"{fmt_bytes(swap.total)} ({swap.percent:.0f}%)")

        # ---- Rede e disco (velocidade = diferenca / tempo decorrido)
        agora = time.time()
        dt = max(agora - self.ult_tempo, 0.001)
        rede = psutil.net_io_counters()
        up = (rede.bytes_sent - self.ult_rede.bytes_sent) / dt
        down = (rede.bytes_recv - self.ult_rede.bytes_recv) / dt
        self.lbl_rede.config(text=f"🌐  ↓ {fmt_bytes(down)}/s    ↑ {fmt_bytes(up)}/s")
        self.ult_rede = rede

        disco = psutil.disk_io_counters()
        if disco and self.ult_disco:
            r = (disco.read_bytes - self.ult_disco.read_bytes) / dt
            w = (disco.write_bytes - self.ult_disco.write_bytes) / dt
            self.lbl_disco_io.config(text=f"💾  Leitura {fmt_bytes(r)}/s    Escrita {fmt_bytes(w)}/s")
        self.ult_disco = disco
        self.ult_tempo = agora

        # ---- Cabecalho
        self.lbl_uptime.config(
            text=f"Ligado há {fmt_tempo(agora - psutil.boot_time())}  •  "
                 f"{len(psutil.pids())} processos")

    def _atualizar(self):
        try:
            self._atualizar_visao_geral()
            self._atualizar_aba_atual()
        except Exception as erro:  # o monitor nunca deve parar por causa de uma leitura
            print(f"Erro na atualizacao: {erro}")
        finally:
            self.tick += 1
            self.after(INTERVALO_MS, self._atualizar)


if __name__ == "__main__":
    PCMonitor().mainloop()