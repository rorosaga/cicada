"""A UDP forwarder the door tests own (G132 ruling 51f): ``UdpWire(door_port)`` stands for a network path to the door.

One upstream socket per client address, as a NAT gives one mapping per flow, so the door sees each client at the
wire's own address and port. ``mode``: ``up`` forwards both ways, ``down`` drops everything (a network that went away
says nothing), ``cut_answers`` forwards toward the door and drops what it answers. ``loss``, ``reorder`` (held back up
to ``reorder_s``) and ``dup`` apply per datagram, both ways, from a seeded generator. ``carried`` counts the bytes
the door sent back through it. Same surface as the TCP ``Wire`` (``port``, ``target``, ``down``, ``up``, ``stop``).
"""
from __future__ import annotations

import heapq
import random
import select
import socket
import threading
import time


class UdpWire:
    def __init__(self, target_port: int, *, loss: float = 0.0, reorder: float = 0.0, dup: float = 0.0,
                 reorder_s: float = 0.01, seed: int = 0):
        self.target = target_port
        self.mode = "up"
        self.loss, self.reorder, self.dup, self.reorder_s = loss, reorder, dup, reorder_s
        self.rnd = random.Random(seed)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.port = self.sock.getsockname()[1]
        self.ups: dict[tuple, socket.socket] = {}
        self.back: dict[socket.socket, tuple] = {}
        self.carried = 0
        self.forwarded = {"toDoor": 0, "toClient": 0, "lost": 0, "reordered": 0, "duplicated": 0}
        self.held: list = []
        self.seq = 0
        self.stopped = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _upstream(self, client: tuple) -> socket.socket:
        up = self.ups.get(client)
        if up is None:
            up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            up.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            up.connect(("127.0.0.1", self.target))
            self.ups[client] = up
            self.back[up] = client
        return up

    def _emit(self, sock: socket.socket, data: bytes, addr) -> None:
        try:
            if addr is None:
                sock.send(data)
            else:
                sock.sendto(data, addr)
        except OSError:
            pass

    def _pass(self, sock: socket.socket, data: bytes, addr) -> None:
        if self.loss and self.rnd.random() < self.loss:
            self.forwarded["lost"] += 1
            return
        copies = 2 if self.dup and self.rnd.random() < self.dup else 1
        if copies == 2:
            self.forwarded["duplicated"] += 1
        for _ in range(copies):
            if self.reorder and self.rnd.random() < self.reorder:
                self.forwarded["reordered"] += 1
                self.seq += 1
                heapq.heappush(self.held, (time.monotonic() + self.rnd.random() * self.reorder_s, self.seq, sock,
                                           data, addr))
            else:
                self._emit(sock, data, addr)

    def _run(self) -> None:
        while not self.stopped:
            wait = 0.05
            if self.held:
                wait = max(0.0, min(wait, self.held[0][0] - time.monotonic()))
            try:
                ready = select.select([self.sock, *self.back], [], [], wait)[0]
            except (OSError, ValueError):
                if self.stopped:
                    return
                continue
            for s in ready:
                try:
                    data, addr = s.recvfrom(65536)
                except OSError:
                    continue
                with self.lock:
                    mode = self.mode
                if s is self.sock:
                    if mode == "down":
                        continue
                    self.forwarded["toDoor"] += 1
                    self._pass(self._upstream(addr), data, None)
                else:
                    if mode in ("down", "cut_answers"):
                        continue
                    self.carried += len(data)
                    self.forwarded["toClient"] += 1
                    self._pass(self.sock, data, self.back[s])
            now = time.monotonic()
            while self.held and self.held[0][0] <= now:
                _t, _s, sock, data, addr = heapq.heappop(self.held)
                self._emit(sock, data, addr)

    def down(self) -> None:
        with self.lock:
            self.mode = "down"

    def up(self) -> None:
        with self.lock:
            self.mode = "up"

    def stop(self) -> None:
        self.stopped = True
        self.thread.join(2)
        for s in [self.sock, *self.back]:
            try:
                s.close()
            except OSError:
                pass
