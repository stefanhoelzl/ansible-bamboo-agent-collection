import time
import argparse
import subprocess
import urllib.request as urlrequest


def get_args_and_cmd():
    parser = argparse.ArgumentParser(description="wait until http server is reachable")
    parser.add_argument("url", type=str)
    parser.add_argument("-t", "--timeout", dest="timeout", default=10 * 60, type=int)
    parser.add_argument(
        "-c", "--status-code", dest="status_code", default=200, type=int
    )
    return parser.parse_known_args()


def wait(request, until) -> int:
    while time.time() < until:
        try:
            return urlrequest.urlopen(request, timeout=(until - time.time())).getcode()
        except:
            continue


if __name__ == "__main__":
    args, cmd = get_args_and_cmd()
    start = time.time()
    status_code = wait(urlrequest.Request(args.url, method="GET"), start + args.timeout)
    if status_code != args.status_code:
        print(f"wrong response code: {status_code}")
        exit(1)
    else:
        print(f"waited { (time.time() - start) / 60 } min for { args.url }", flush=True)
        if cmd:
            exit(subprocess.run(cmd).returncode)
