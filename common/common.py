import logging
import csv
import os
import random
import time
# Rashed-Step 24.D-10-19-2026: `import pandas as pd` removed - nothing used it, and it was
# ~2.7 s of every process start (each parallel worker re-imports this module).
import simpy


# Rashed-Step 1.A-12-26-2025-start
from typing import Tuple
import math
# Rashed-Step 1.A-12-26-2025-end


from dataclasses import dataclass, field
from typing import Dict, List, Optional

# from .Times import *
from datetime import datetime

# Rashed-Step 8.A-08-06-2026-start
from common.packet import Packet
# Rashed-Step 8.A-08-06-2026-end


output_csv = "lool.csv"
file_log_name = f"{'log/'+datetime.today().strftime('%Y-%m-%d-%H-%M-%S')}.log"




colors = [
    "\033[30m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[34m",
    "\033[35m",
    "\033[36m",
    "\033[37m",
]  # colors to distinguish stations in output

typ_filename = "RS_coex_1sta_1wifi2.log"

# Rashed-Step 24.A-10-19-2026-start
# The per-event log file used to be opened at import (logging.basicConfig
# here), so every run - and every parallel worker - wrote log/<time>.log:
# 45 % of a run's time and 20-30 MB per 100 simulated seconds. Now no file
# unless enable_file_log() is called (singleRun.py / singleRunNR.py
# --log-file); log() returns at once while it is off. Printed results don't
# depend on it.
logger = logging.getLogger()
_FILE_LOG_ON = False


def enable_file_log(path: str = None, level: str = "INFO") -> str:
    """Write log() lines to `path` (default log/<timestamp>.log, as before)
    at `level` ("INFO" / "DEBUG"). Returns the path."""
    global _FILE_LOG_ON
    path = path or file_log_name
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    logging.basicConfig(filename=path, format='%(asctime)s %(message)s', filemode='w', force=True)
    logger.setLevel(getattr(logging, level))
    _FILE_LOG_ON = True
    return path


def file_log_enabled() -> bool:
    return _FILE_LOG_ON
# Rashed-Step 24.A-10-19-2026-end


def log(gnb, mes: str) -> None:
    if not _FILE_LOG_ON:  # Rashed-Step 24.A-10-19-2026
        return
    logger.info(
        f"{gnb.col}Time: {gnb.env.now} Station: {gnb.name} Message: {mes}"
    )


gap = True

big_num = 100000  # some big number for quesing in peeemtive resources - big starting point


# Rashed-Step 1.A-12-26-2025-start
Pos = Tuple[float, float]

def dist(a: Pos, b: Pos) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def rand_pos(area_w: float, area_h: float) -> Pos:
    return (random.uniform(0, area_w), random.uniform(0, area_h))

# Rashed-Step 1.A-12-26-2025-end



# Rashed-Step 2.B-12-30-2025-start
# @dataclass()
# class Frame:
#     frame_time: int  # time of the frame
#     station_name: str  # name of the owning it station
#     col: str  # output color
#     data_size: int  # payload size
#     t_start: int  # generation time
#     number_of_retransmissions: int = 0  # retransmissions count
#     t_end: int = None  # sent time
#     t_to_send: int = None  # how much time it took to sent successfully

#     def __repr__(self):
#         return (self.col + "Frame: start=%d, end=%d, frame_time=%d, retransmissions=%d"
#                 % (self.t_start, self.t_end, self.t_to_send, self.number_of_retransmissions)
#                 )
 # Rashed-Step 2.B-12-30-2025-end   

# Rashed-Step 2.B_1-12-30-2025-start
@dataclass()
class Frame:
    frame_time: int
    station_name: str
    col: str
    data_size: int
    t_start: int
    number_of_retransmissions: int = 0
    t_end: int = None
    t_to_send: int = None

    # NEW: topology + link info
    tx_pos: Pos = None
    rx_name: str = None
    rx_pos: Pos = None
    distance_m: float = None
    pr_dbm: float = None

    # Rashed-Step 8.A-08-06-2026-start
    # Optional reference to the Packet this Frame is carrying - None by
    # default so every existing caller that constructs a Frame directly
    # (there are none outside wifi.py/attacker/*.py, but this keeps the
    # default fully backward compatible either way) is unaffected. Step
    # 8.B is what actually populates this field.
    packet: Optional[Packet] = None
    # Rashed-Step 8.A-08-06-2026-end

    # Rashed-Step 8.F-08-06-2026-start
    # Optional reference to the ACK Packet (packet_type="ACK") sent back
    # in response to `packet` above, once/if it's successfully
    # delivered. None by default (no ACK exists for a frame that never
    # succeeded, or before wifi.WiFi.sent_completed() constructs one) -
    # see that method and send_frame() for where this is populated.
    # NR-U has no equivalent field: it has no ACK-frame concept at all
    # (success/failure is decided purely by end-of-transmission SINR,
    # no separate ACK phase in this simulator - see Step 8.txt).
    ack_packet: Optional[Packet] = None
    # Rashed-Step 8.F-08-06-2026-end
# Rashed-Step 2.B_1-12-30-2025-end