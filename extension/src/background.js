// Intentionally empty, stateless MV3 background worker.
//
// The extension does all its work inside the popup's click handler
// (FRG-EXT-001). No listeners, alarms, cookie reads, or network calls run
// here — the worker exists only to satisfy the MV3 background slot and holds
// no state between invocations.
