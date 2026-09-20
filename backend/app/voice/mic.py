"""Who has the microphone right now.

A USB microphone can only be opened by one process at a time, and three things
want it: a tap-to-talk (or wake-word) conversation, the always-on wake-word
listener, and the short "say stop" window while an alarm rings. The wake-word
listener is paused around the other two (see WakeWordListener.pause); this lock
is what stops the other two from opening the device at the same instant.
"""

import asyncio

mic_lock = asyncio.Lock()
