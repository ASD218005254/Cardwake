#!/usr/bin/env python3
"""Generate rsrc_windows_amd64.syso (icon + UAC manifest) so `go build` embeds them in Cardwake.exe.
Needs Pillow only to draw the icon.  Usage: python3 tools/mksyso.py"""
import io, struct, sys, os
from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]
VERSION = (1, 1, 0, 0)

def draw_icon(px):
    k = 8; W = px * k; u = W / 64.0
    # gradient
    grad = Image.new('RGB', (W, W))
    stops = [(0, (0x5e, 0xea, 0xd4)), (.5, (0x38, 0xbd, 0xf8)), (1, (0x8b, 0x5c, 0xf6))]
    gp = grad.load()
    for y in range(W):
        for x in range(W):
            t = (x + y) / (2.0 * (W - 1))
            for i in range(len(stops) - 1):
                if stops[i][0] <= t <= stops[i + 1][0]:
                    a, b = stops[i], stops[i + 1]; f = (t - a[0]) / (b[0] - a[0])
                    gp[x, y] = tuple(int(a[1][j] + (b[1][j] - a[1][j]) * f) for j in range(3)); break
    mask = Image.new('L', (W, W), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((12 * u, 6 * u, 50 * u, 58 * u), radius=4 * u, fill=255)
    md.polygon([(38 * u, 5 * u), (51 * u, 5 * u), (51 * u, 18 * u)], fill=0)
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0)); img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    pts = [(19, 36), (26, 36), (30, 27), (36, 45), (40, 36), (45, 36)]
    pts = [(x * u, y * u) for x, y in pts]
    w = 3.4 * u
    d.line(pts, fill=(5, 18, 26, 255), width=int(w), joint='curve')
    for x, y in pts:
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=(5, 18, 26, 255))
    return img.resize((px, px), Image.LANCZOS)

def png_bytes(im):
    b = io.BytesIO(); im.save(b, 'PNG', optimize=True); return b.getvalue()

MANIFEST = ('''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="Cardwake.App" version="%d.%d.%d.%d" processorArchitecture="amd64"/>
  <description>Cardwake - memory card toolkit</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security><requestedPrivileges><requestedExecutionLevel level="requireAdministrator" uiAccess="false"/></requestedPrivileges></security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
    </application>
  </compatibility>
</assembly>
''' % VERSION).encode('utf-8')

def align(n, a=4): return (n + a - 1) // a * a

def build():
    pngs = [(s, png_bytes(draw_icon(s))) for s in SIZES]
    grp = struct.pack('<HHH', 0, 1, len(pngs))
    leaves = []                       # (type, id, data)
    for i, (s, data) in enumerate(pngs, start=1):
        grp += struct.pack('<BBBBHHIH', 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), i)
        leaves.append((3, i, data))
    leaves.append((14, 1, grp))
    leaves.append((24, 1, MANIFEST))
    types = {}
    for t, i, d in leaves: types.setdefault(t, []).append((i, d))
    # sizes of directory area
    def dsz(n): return 16 + 8 * n
    off = dsz(len(types))
    type_off = {}
    for t in sorted(types):
        type_off[t] = off; off += dsz(len(types[t]))
    name_off = {}
    for t in sorted(types):
        for i, d in sorted(types[t]):
            name_off[(t, i)] = off; off += dsz(1)
    entry_off = {}
    for t in sorted(types):
        for i, d in sorted(types[t]):
            entry_off[(t, i)] = off; off += 16
    data_off = {}
    for t in sorted(types):
        for i, d in sorted(types[t]):
            off = align(off); data_off[(t, i)] = off; off += len(d)
    total = align(off)
    sec = bytearray(total); relocs = []
    def dirhdr(pos, n): struct.pack_into('<IIHHHH', sec, pos, 0, 0, 0, 0, 0, n)
    dirhdr(0, len(types)); p = 16
    for t in sorted(types):
        struct.pack_into('<II', sec, p, t, 0x80000000 | type_off[t]); p += 8
    for t in sorted(types):
        dirhdr(type_off[t], len(types[t])); p = type_off[t] + 16
        for i, d in sorted(types[t]):
            struct.pack_into('<II', sec, p, i, 0x80000000 | name_off[(t, i)]); p += 8
    for t in sorted(types):
        for i, d in sorted(types[t]):
            dirhdr(name_off[(t, i)], 1)
            struct.pack_into('<II', sec, name_off[(t, i)] + 16, 0x0409, entry_off[(t, i)])
            eo = entry_off[(t, i)]
            struct.pack_into('<IIII', sec, eo, data_off[(t, i)], len(d), 0, 0)
            relocs.append(eo)
            sec[data_off[(t, i)]:data_off[(t, i)] + len(d)] = d
    # COFF object
    hdr_len = 20 + 40
    reloc_ptr = hdr_len + total
    sym_ptr = reloc_ptr + 10 * len(relocs)
    out = bytearray()
    out += struct.pack('<HHIIIHH', 0x8664, 1, 0, sym_ptr, 1, 0, 0)
    out += struct.pack('<8sIIIIIIHHI', b'.rsrc', 0, 0, total, hdr_len, reloc_ptr, 0, len(relocs), 0, 0xC0000040)
    out += sec
    for r in relocs: out += struct.pack('<IIH', r, 0, 3)     # IMAGE_REL_AMD64_ADDR32NB -> symbol 0 (.rsrc)
    out += struct.pack('<8sIhHBB', b'.rsrc', 0, 1, 0, 3, 0)
    out += struct.pack('<I', 4)
    return bytes(out), pngs

if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    data, pngs = build()
    dst = os.path.join(here, '..', 'rsrc_windows_amd64.syso')
    open(dst, 'wb').write(data)
    pngs[-1][1] and open(os.path.join(here, '..', 'cardwake_icon_256.png'), 'wb').write(pngs[-1][1])
    print('wrote', os.path.normpath(dst), len(data), 'bytes;', len(pngs), 'icon sizes')
