Run `main.py test` to run the test suite

Run `main.py` to load the data and drop into an interactive shell

Use `help` for help

To run it so that other can connect via Telnet run
`ncat -t -k -v -l -e "python main.py" 3777`
(needs ncat from the nmap package)

Explanation for the ncat options:

```
-t Answer Telnet negotiations
-k Accept multiple connections in listen mode
-v Set verbosity level (can be used several times)
-l Bind and listen for incoming connections
-e Executes the given command
```