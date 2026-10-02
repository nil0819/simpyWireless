# Rashed-Step 16.E-10-02-2026-start
"""
Step 16.E: the RAN side of the UPF user-plane gate (Project details/
Step 16.txt). A UE handed to the 5G Core (core.network.CoreNetwork.
start_ue()) may only carry DATA once its PDU session is ACTIVE; every
other UE behaves exactly as before.

Duck-typed on purpose: start_ue() leaves a back-reference
ue.core_network, and this module only calls its user_plane_allows(name).
So nr/ and nru/ never import core/, and a UE without that attribute is
always allowed - the same default-allow contract rrc_state uses
(getattr(ue, "rrc_state", RrcState.CONNECTED)).

Used by: nr.nr.GnbLicensedNR._run_dl_slot()/_run_ul_slot(), nru.nru.Gnb's
downlink destination pick, and (via the _user_plane_event hook below)
nru.ue.NrUE.start_uplink().
"""
from typing import Any


def user_plane_allows(ue: Any) -> bool:
    core = getattr(ue, "core_network", None)
    return core is None or core.user_plane_allows(ue.name)
# Rashed-Step 16.E-10-02-2026-end
