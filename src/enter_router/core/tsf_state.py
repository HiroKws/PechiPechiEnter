"""er_tip（TSF テキストサービス）が書いた共有メモリの解析（純粋・OS 非依存）.

レイアウトは ``tsf/er_tip.cpp`` と一致（パック済み・固定幅）::

    Shared { int32 magic('ERTS'=0x53545245); int64 updated; Slot[32] }
    Slot   { int32 tid; int32 composing; int64 tick; int32 seq }

``tick`` は ``GetTickCount64()`` のミリ秒。読む側も同じ時計で比較する。

この module は bytes を受けて判定するだけ（テスト可能）。実際のメモリ読み出しは
``platform/tsf_state.py``。
"""
from __future__ import annotations

import struct

MAGIC = 0x53545245          # 'ERTS'
SLOTS = 32
HEAD = struct.Struct("<iq")          # magic, updated
SLOT = struct.Struct("<iiqi")        # tid, composing, tick, seq
SIZE = HEAD.size + SLOT.size * SLOTS

#: これより古い記録は「読めない」とみなす（er_tip は 40ms ごとに更新する）
DEFAULT_MAX_AGE_MS = 500


def parse(buf: bytes) -> tuple[int, dict[int, tuple[bool, int]]]:
    """``(updated_tick, {tid: (composing, tick)})``. 壊れていれば ``(-1, {})``."""
    if len(buf) < SIZE:
        return -1, {}
    magic, updated = HEAD.unpack_from(buf, 0)
    if magic != MAGIC:
        return -1, {}
    slots: dict[int, tuple[bool, int]] = {}
    for i in range(SLOTS):
        tid, composing, tick, _seq = SLOT.unpack_from(buf, HEAD.size + i * SLOT.size)
        if tid:
            slots[int(tid)] = (bool(composing), int(tick))
    return int(updated), slots


def composing_for(buf: bytes, tid: int, now_tick: int,
                  max_age_ms: int = DEFAULT_MAX_AGE_MS) -> bool | None:
    """``tid`` の未確定状態。``True``=日本語入力中 / ``False``=未確定なし / ``None``=不明.

    ``None`` は「er_tip がまだ書き込んでいない・このスレッドを観測していない・
    記録が古い（max_age_ms より前）」のいずれか。呼び側は None のときだけ従来の
    安全側（日本語入力中とみなして素通し）にフォールバックする。
    """
    _updated, slots = parse(buf)
    found = slots.get(int(tid))
    if found is None:
        return None
    composing, tick = found
    if now_tick - tick > max_age_ms or now_tick < tick - max_age_ms:
        return None
    return composing
