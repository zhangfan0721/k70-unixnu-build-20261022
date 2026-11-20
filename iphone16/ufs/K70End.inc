// SPDX-License-Identifier: BSD-2-Clause-Patent
static bool hostEnd(const char **why) {
    if(!gOwnStarted)return true; // Never repeat a failed initial stop.
    if(gCleanupAttempted){*why="own list stop already attempted";return false;}
    gCleanupAttempted=true;gPhase=K70HostPhase::Ending;
    if(!hostControlHealthy() || !hcIdentity(true)) {
        *why="own list identity unknown; DMA retained";return false;
    }
    hostWrite(0x60,0);
    if(!hostControlHealthy() || !hostWaitRegister(0x60,1,0)) {
        *why="own list stop not confirmed; DMA retained";return false;
    }
    if(!hostState(0x58,0) || !hostState(0x78,0) || !hcIdentity(true)) {
        *why="own list stopped with outstanding/changed state; DMA retained";return false;
    }
    gPhase=K70HostPhase::Ended;
    return hostControlHealthy();
}
