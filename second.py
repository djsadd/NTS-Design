#!/usr/bin/env python3
"""
encrypt_app.py
Простое GUI-приложение для шифрования/дешифрования файлов.
Не для production; учебный, простой алгоритм на основе PBKDF2+SHA256 + XOR keystream.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import hashlib
import os
import struct

MAGIC = b'ENCAPP1'            # 7 bytes signature
SALT_SIZE = 16
PBKDF2_ITERS = 100_000
KEY_LEN = 32
MARKER = b'BEGINFILE'         # проверочный маркер
CHUNK = 64 * 1024             # 64 KB

def derive_key(password: str, salt: bytes, iters: int) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iters, dklen=KEY_LEN)

def keystream_blocks(key: bytes):
    """Генерирует последовательные 32-байт блоки SHA256(key || counter)."""
    counter = 0
    while True:
        ctr_bytes = struct.pack('>Q', counter)  # 8 bytes counter
        h = hashlib.sha256(key + ctr_bytes).digest()
        yield h
        counter += 1

def stream_xor(data_iter, key):
    """XOR-стриминг: принимает итератор байтовых блоков, выдаёт XORed блоки."""
    ks_gen = keystream_blocks(key)
    ks_buf = b''
    ks_pos = 0

    for block in data_iter:
        out = bytearray(len(block))
        i = 0
        while i < len(block):
            if ks_pos >= len(ks_buf):
                ks_buf = next(ks_gen)
                ks_pos = 0
            take = min(len(block) - i, len(ks_buf) - ks_pos)
            for j in range(take):
                out[i + j] = block[i + j] ^ ks_buf[ks_pos + j]
            i += take
            ks_pos += take
        yield bytes(out)

def encrypt_file(in_path, out_path, password, iters=PBKDF2_ITERS):
    salt = os.urandom(SALT_SIZE)
    key = derive_key(password, salt, iters)

    # write header: MAGIC | salt | iters (4) | name_len (2) | name (utf-8)
    name = os.path.basename(in_path).encode('utf-8')
    header = bytearray()
    header += MAGIC
    header += salt
    header += struct.pack('>I', iters)
    header += struct.pack('>H', len(name))
    header += name

    with open(in_path, 'rb') as fin, open(out_path, 'wb') as fout:
        fout.write(header)

        # stream: first emit MARKER then file bytes
        def chunks_with_marker():
            yield MARKER
            while True:
                b = fin.read(CHUNK)
                if not b:
                    break
                yield b

        for out_block in stream_xor(chunks_with_marker(), key):
            fout.write(out_block)

def decrypt_file(in_path, out_dir, password):
    with open(in_path, 'rb') as fin:
        magic = fin.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError("Неверный формат файла (magic mismatch).")

        salt = fin.read(SALT_SIZE)
        iters_bytes = fin.read(4)
        iters = struct.unpack('>I', iters_bytes)[0]
        name_len_bytes = fin.read(2)
        name_len = struct.unpack('>H', name_len_bytes)[0]
        name = fin.read(name_len).decode('utf-8')

        key = derive_key(password, salt, iters)

        # read rest in chunks, decrypting; first chunk must start with MARKER
        def encrypted_chunks():
            while True:
                b = fin.read(CHUNK)
                if not b:
                    break
                yield b

        out_gen = stream_xor(encrypted_chunks(), key)
        first = next(out_gen, None)
        if first is None:
            raise ValueError("Пустой файл после заголовка.")

        if not first.startswith(MARKER):
            raise ValueError("Похоже неверный пароль или файл повреждён (маркер не найден).")

        # save remaining bytes (after marker) + subsequent blocks
        out_path = os.path.join(out_dir, name)
        with open(out_path, 'wb') as fout:
            fout.write(first[len(MARKER):])
            for block in out_gen:
                fout.write(block)
        return out_path

# --- GUI ----
class App:
    def __init__(self, root):
        self.root = root
        root.title("EncryptApp — простой шифратор")
        root.geometry("520x220")
        self.filepath = None

        tk.Label(root, text="Файл:").grid(row=0, column=0, sticky='w', padx=8, pady=8)
        self.file_entry = tk.Entry(root, width=50)
        self.file_entry.grid(row=0, column=1, padx=8, pady=8, columnspan=2)
        tk.Button(root, text="Открыть...", command=self.browse_file).grid(row=0, column=3, padx=8)

        tk.Label(root, text="Пароль:").grid(row=1, column=0, sticky='w', padx=8)
        self.pw_entry = tk.Entry(root, show='*', width=30)
        self.pw_entry.grid(row=1, column=1, padx=8, pady=6, sticky='w')

        tk.Button(root, text="Шифровать → сохранить .encapp", command=self.encrypt_clicked).grid(row=2, column=1, pady=12)
        tk.Button(root, text="Дешифровать .encapp", command=self.decrypt_clicked).grid(row=2, column=2, pady=12)

        self.status = tk.Label(root, text="Готов.", anchor='w')
        self.status.grid(row=3, column=0, columnspan=4, sticky='we', padx=8)

    def browse_file(self):
        f = filedialog.askopenfilename()
        if f:
            self.filepath = f
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, f)

    def encrypt_clicked(self):
        path = self.file_entry.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Ошибка", "Выберите существующий файл для шифрования.")
            return
        pw = self.pw_entry.get()
        if not pw:
            messagebox.showerror("Ошибка", "Введите пароль.")
            return
        default_name = os.path.basename(path) + ".encapp"
        outpath = filedialog.asksaveasfilename(defaultextension=".encapp", initialfile=default_name)
        if not outpath:
            return
        try:
            self.status.config(text="Шифрование...")
            self.root.update_idletasks()
            encrypt_file(path, outpath, pw)
            self.status.config(text=f"Файл зашифрован и сохранён: {outpath}")
            messagebox.showinfo("Готово", "Шифрование завершено.")
        except Exception as e:
            messagebox.showerror("Ошибка при шифровании", str(e))
            self.status.config(text="Ошибка.")

    def decrypt_clicked(self):
        path = filedialog.askopenfilename(filetypes=[("EncApp files", "*.encapp"), ("All files", "*.*")])
        if not path:
            return
        pw = self.pw_entry.get()
        if not pw:
            messagebox.showerror("Ошибка", "Введите пароль.")
            return
        outdir = filedialog.askdirectory(title="Папка для сохранения расшифрованного файла")
        if not outdir:
            return
        try:
            self.status.config(text="Дешифрование...")
            self.root.update_idletasks()
            out_path = decrypt_file(path, outdir, pw)
            self.status.config(text=f"Файл расшифрован: {out_path}")
            messagebox.showinfo("Готово", f"Файл расшифрован и сохранён:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Ошибка при дешифровании", str(e))
            self.status.config(text="Ошибка.")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
