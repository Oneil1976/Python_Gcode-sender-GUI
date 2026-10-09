"""
GUI (tkinter) na odosielanie G-code súborov do dosky s GRBL.

- Tlačidlá Inicializácia / Program 1 / Program 2 odošlú priradený súbor.
- Tlačidlo Nastavenia otvorí okno, kde sa nastavuje COM port, baud rate
  a cesta k jednotlivým súborom. Nastavenia sa ukladajú do
  grbl_sender_config.json (v priečinku so skriptom).

Závislosti:  pip install pyserial
"""

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import serial
from serial.tools import list_ports

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "grbl_sender_config.json")

# Názvy tlačidiel (poradie = poradie v okne)
NAZVY = ["Inicializácia", "Spustiť program 1", "Spustiť program 2"]

BAUD_HODNOTY = [9600, 19200, 38400, 57600, 115200, 230400, 250000]

DEFAULT_CONFIG = {
    "port": "COM3",       # Linux: "/dev/ttyUSB0" alebo "/dev/ttyACM0"
    "baud": 115200,       # štandard pre GRBL 1.1
    "subory": {
        "Inicializácia": "init.gcode",
        "Spustiť program 1": "program1.gcode",
        "Spustiť program 2": "program2.gcode",
    },
}


# ------------------------------ KONFIGURÁCIA ------------------------------
def nacitaj_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # hlboká kópia
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            ulozene = json.load(f)
        cfg["port"] = ulozene.get("port", cfg["port"])
        cfg["baud"] = int(ulozene.get("baud", cfg["baud"]))
        cfg["subory"].update(ulozene.get("subory", {}))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass
    return cfg


def uloz_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ------------------------------ GRBL KOMUNIKÁCIA ------------------------------
def vycisti_riadok(riadok: str) -> str:
    """Odstráni komentáre a biele znaky z riadku G-code."""
    riadok = re.sub(r"\(.*?\)", "", riadok)  # komentáre v zátvorkách
    riadok = riadok.split(";")[0]            # komentáre za bodkočiarkou
    return riadok.strip()


def odosli_gcode(cesta: str, port: str, baud: int, log):
    """Odošle súbor riadok po riadku a čaká na 'ok' od GRBL."""
    with open(cesta, "r", encoding="utf-8") as f:
        riadky = [vycisti_riadok(r) for r in f]
    riadky = [r for r in riadky if r]

    log(f"Pripájam sa na {port} @ {baud}...")
    with serial.Serial(port, baud, timeout=1) as s:
        # Prebudenie GRBL
        s.write(b"\r\n\r\n")
        time.sleep(2)
        s.reset_input_buffer()

        celkom = len(riadky)
        for i, riadok in enumerate(riadky, start=1):
            s.write((riadok + "\n").encode("ascii"))

            while True:
                odpoved = s.readline().decode("ascii", errors="ignore").strip()
                if not odpoved:
                    continue
                if odpoved == "ok":
                    break
                if odpoved.startswith("error"):
                    raise RuntimeError(f"Riadok {i}: '{riadok}' -> {odpoved}")
                log(f"GRBL: {odpoved}")

            log(f"[{i}/{celkom}] {riadok}")

    log("Hotovo.")


# ------------------------------ OKNO NASTAVENÍ ------------------------------
class NastaveniaOkno(tk.Toplevel):
    def __init__(self, rodic, cfg: dict, pri_ulozeni):
        super().__init__(rodic)
        self.title("Nastavenia")
        self.resizable(False, False)
        self.transient(rodic)

        self.cfg = cfg
        self.pri_ulozeni = pri_ulozeni

        # --- Komunikácia ---
        komunikacia = ttk.LabelFrame(self, text="Komunikácia")
        komunikacia.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        ttk.Label(komunikacia, text="COM port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_var = tk.StringVar(value=cfg["port"])
        self.port_box = ttk.Combobox(komunikacia, textvariable=self.port_var, width=22)
        self.port_box.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(komunikacia, text="Obnoviť", command=self.obnov_porty).grid(row=0, column=2, padx=5)

        ttk.Label(komunikacia, text="Baud rate:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.baud_var = tk.StringVar(value=str(cfg["baud"]))
        ttk.Combobox(komunikacia, textvariable=self.baud_var, width=22,
                     values=[str(b) for b in BAUD_HODNOTY]).grid(row=1, column=1, padx=5, pady=5)

        # --- Súbory ---
        subory = ttk.LabelFrame(self, text="G-code súbory")
        subory.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")

        self.cesty = {}
        for r, nazov in enumerate(NAZVY):
            ttk.Label(subory, text=nazov + ":").grid(row=r, column=0, padx=5, pady=5, sticky="w")
            var = tk.StringVar(value=cfg["subory"].get(nazov, ""))
            self.cesty[nazov] = var
            ttk.Entry(subory, textvariable=var, width=45).grid(row=r, column=1, padx=5, pady=5)
            ttk.Button(subory, text="Vybrať...",
                       command=lambda n=nazov: self.vyber_subor(n)).grid(row=r, column=2, padx=5)

        # --- Tlačidlá ---
        tlacidla = ttk.Frame(self)
        tlacidla.grid(row=2, column=0, pady=(0, 10))
        ttk.Button(tlacidla, text="Uložiť", command=self.uloz).pack(side=tk.LEFT, padx=5)
        ttk.Button(tlacidla, text="Zrušiť", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.obnov_porty()
        self.grab_set()  # modálne okno

    def obnov_porty(self):
        porty = [p.device for p in list_ports.comports()]
        self.port_box["values"] = porty

    def vyber_subor(self, nazov: str):
        cesta = filedialog.askopenfilename(
            parent=self,
            title=f"Vyberte súbor pre: {nazov}",
            filetypes=[("G-code", "*.gcode *.nc *.ngc *.gc *.txt"), ("Všetky súbory", "*.*")],
        )
        if cesta:
            self.cesty[nazov].set(cesta)

    def uloz(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("Nastavenia", "Vyberte COM port.", parent=self)
            return
        try:
            baud = int(self.baud_var.get())
            if baud <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Nastavenia", "Baud rate musí byť kladné celé číslo.", parent=self)
            return

        self.cfg["port"] = port
        self.cfg["baud"] = baud
        for nazov, var in self.cesty.items():
            self.cfg["subory"][nazov] = var.get().strip()

        uloz_config(self.cfg)
        self.pri_ulozeni()
        self.destroy()


# ------------------------------ HLAVNÉ OKNO ------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GRBL odosielač G-code")
        self.geometry("620x380")

        self.cfg = nacitaj_config()
        self.fronta = queue.Queue()
        self.tlacidla = []

        rám = tk.Frame(self)
        rám.pack(pady=10)

        for nazov in NAZVY:
            b = tk.Button(rám, text=nazov, width=18, height=2,
                          command=lambda n=nazov: self.spusti(n))
            b.pack(side=tk.LEFT, padx=8)
            self.tlacidla.append(b)

        self.btn_nastavenia = tk.Button(self, text="⚙ Nastavenia", command=self.otvor_nastavenia)
        self.btn_nastavenia.pack(pady=(0, 5))

        self.stav = tk.Label(self, anchor="w")
        self.stav.pack(fill=tk.X, padx=10)
        self.aktualizuj_stav()

        self.vystup = scrolledtext.ScrolledText(self, state="disabled", height=12)
        self.vystup.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.after(100, self.spracuj_frontu)

    def aktualizuj_stav(self):
        self.stav.config(text=f"Port: {self.cfg['port']}   |   Baud: {self.cfg['baud']}")

    def otvor_nastavenia(self):
        NastaveniaOkno(self, self.cfg, self.aktualizuj_stav)

    # ---- logovanie (bezpečné pre vlákna cez frontu) ----
    def log(self, text: str):
        self.fronta.put(("log", text))

    def spracuj_frontu(self):
        try:
            while True:
                typ, data = self.fronta.get_nowait()
                if typ == "log":
                    self.vystup.config(state="normal")
                    self.vystup.insert(tk.END, data + "\n")
                    self.vystup.see(tk.END)
                    self.vystup.config(state="disabled")
                elif typ == "koniec":
                    self.nastav_tlacidla(tk.NORMAL)
                elif typ == "chyba":
                    self.nastav_tlacidla(tk.NORMAL)
                    messagebox.showerror("Chyba", data)
        except queue.Empty:
            pass
        self.after(100, self.spracuj_frontu)

    def nastav_tlacidla(self, stav):
        for b in self.tlacidla + [self.btn_nastavenia]:
            b.config(state=stav)

    # ---- spustenie odosielania v samostatnom vlákne ----
    def spusti(self, nazov: str):
        cesta = self.cfg["subory"].get(nazov, "").strip()
        if not cesta:
            messagebox.showwarning("Chýba súbor",
                                   f"Pre '{nazov}' nie je nastavený súbor.\nOtvorte Nastavenia.")
            return

        self.nastav_tlacidla(tk.DISABLED)
        self.log(f"--- {nazov}: {cesta} ---")
        threading.Thread(
            target=self.pracovne_vlakno,
            args=(cesta, self.cfg["port"], self.cfg["baud"]),
            daemon=True,
        ).start()

    def pracovne_vlakno(self, cesta: str, port: str, baud: int):
        try:
            odosli_gcode(cesta, port, baud, self.log)
            self.fronta.put(("koniec", None))
        except FileNotFoundError:
            self.log(f"Súbor '{cesta}' sa nenašiel.")
            self.fronta.put(("chyba", f"Súbor '{cesta}' sa nenašiel."))
        except serial.SerialException as e:
            self.log(f"Chyba sériového portu: {e}")
            self.fronta.put(("chyba", f"Chyba sériového portu:\n{e}"))
        except Exception as e:
            self.log(f"Chyba: {e}")
            self.fronta.put(("chyba", str(e)))


if __name__ == "__main__":
    App().mainloop()
