"""Run an adapter's cut list: for each cut, start the update from the same flash
image, pull the plug, power back up and ask whether the device recovered.

The work is in brickproof.campaign, one module per part: what a run returns (results),
the uninterrupted update (golden), judging one result (judge), power cuts and torn
states (cuts), damaged images, bit errors and a broken link (faults), cuts during a
recovery (depth), the whole campaign (core) and the emulators it runs on (bringup).
This module keeps the names other code has always imported from here."""
# ruff: noqa: F401
from brickproof.campaign.bringup import _bring_up, find_emulator, run, start_session
from brickproof.campaign.core import _cuts_to_run, _past_the_end, auto_real_every, campaign
from brickproof.campaign.cuts import run_computed, run_cut, run_torn, soak
from brickproof.campaign.depth import _digest, _recovery_trace, explore, run_deep
from brickproof.campaign.faults import (bit_errors, content_faults, link_cuts, link_points,
                                        run_bit_error, run_content, run_link)
from brickproof.campaign.golden import Golden
from brickproof.campaign.judge import _failed, _fault_message, _hang_confirmed, _rewind_program, _verdict
from brickproof.campaign.results import BASELINE, KIND_NAMES, CutResult, Outcome, SelfCheckFailed, as_dict
from brickproof.engine.session import find_renode
