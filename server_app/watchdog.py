import signal
import time
import atexit

class Watchdog:

    def __init__(self):
        signal.signal(signal.SIGALRM, self.handler)

    def register(self, func, value):
        self.func = func
        self.value = value
        #atexit.register(func, value)

    #signum, frame
    def handler(self, signum, frame):
          print("Timeout is over!")
          print('Calling shutdown handler!')
          self.func(self.value)
          #BenchmarkResults.results(current_scene)

          exit(1)
          raise Exception("end of time")

    def extend(self, time, value):
        self.num = value
        return signal.alarm(10)

    def reset_and_extend(self, time, value):
        self.num = value
        signal.alarm(0)
        return signal.alarm(time)

def testf(number):
      print("Meaning of life is %s" % number)

if __name__ == '__main__':
    while(True):
        print("start")
        w = Watchdog(testf, 42)
        w.extend(10)
        time.sleep(15)
