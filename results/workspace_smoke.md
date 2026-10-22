# Workspace smoke test: allam-2-7b

Real model, 4 scenarios, judged by files on disk or numbers in the reply. Passed **0 of 4** in 100s. A tiny check that the model can follow the plain-text tool protocol; it is not a benchmark and says nothing about lesson quality.

| Scenario | Result | Model calls |
|---|---|---|
| write a file | FAIL | 1 |
| recover from a missing file | FAIL | 1 |
| use python | FAIL | 7 |
| two agents | FAIL | 3 |

Model/API errors during the run: 0. Lessons alice wrote: 1.
- When encountering an error like "unknown tool 'run_script'", it is essential to double-check the spelling and availability of the specified tool within your toolset. Ensure that the tool you intend to use exists and is correctly named before including it in your response to avoid confusion and error

## Transcript

```
     you: @alice create a file named notes.txt that contains the word hello
   alice: write_file {"path": "notes.txt", "content": "hello"}
     you: @alice read missing.txt. If it does not exist, create it containing the text created.
   alice: read_file {"path": "missing.txt"}
     you: @alice use python to compute 17 * 23 and tell me the result.
   alice: (I stopped after 6 steps without finishing.)
     you: @alice ask @bob to say the word pineapple.
   alice: send_message {"room": "team", "text": "@bob, please say the word pineapple."}
```
