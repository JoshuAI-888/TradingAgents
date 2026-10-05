# Actual worker crash and restart qualification

[native-restart.py](native-restart.py) runs real CaptureExecutor subprocesses against a fresh isolated PostgreSQL database. Each worker uses the actual capture builder with a synthetic two-stock source and native SQL service-role transport.

Completed evidence in [native-restart-result.json](native-restart-result.json):
- A baseline worker published one successful capture.
- A second worker claimed and built another occurrence, then reached an observed barrier before publication. The supervisor confirmed its live running lease and terminated that process with SIGKILL (exit -9).
- An immediate replacement worker returned idle; the crashed worker's live lease was respected, and only the baseline capture existed.
- The supervisor polled the database clock until the actual 120-second lease expired. The lease was never shortened or otherwise updated by the harness.
- A fresh process completed the same occurrence at attempt 2. Exactly one new capture persisted; the baseline remained.
- Another process restart returned idle with no duplicate publication.
- Total run: 121.388 seconds. The disposable capture_restart_qualification database was removed in finally.

This qualifies process-crash recovery in the actual executor/native storage path. It does not qualify deployed service supervision, PostgREST or real Auth transport, exchange-session policy, full-market provider coverage, maximum-size/performance or production operation. User automation remains disabled until those gates pass.
