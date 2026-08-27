# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""LAN team-collaboration support (协作码模式).

One machine hosts a team (4-digit join code, UDP discovery on the local
network); others join with the code. Shared across the team: a host-side
shared folder (bidirectional) and host-selected LLM models (requests are
relayed through the host, so API keys never leave it). Chats and sessions
always stay on each member's own machine.
"""

from data_formulator.team.service import team_service  # noqa: F401
