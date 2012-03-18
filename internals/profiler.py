import time

from lib.spark.spark import spark_string


IDLE_SPARK_DELAY = 10  # In seconds
IDLE_LOG_CAP = (60 / IDLE_SPARK_DELAY) * 5  # Five minutes


class Profiler(object):

    def __init__(self):
        now = time.time()
        self.start_time = now

        self.times = {}
        self.last_time = now
        self.last_action = "startup"

        self.idle_time = 0
        self.total_idle_time = 0
        self.idle_log = []
        self.last_idle_print = now

    def clear(self):
        """Clear the logged time data."""
        self.times = {}

    def reset_time(self):
        """Reset the running time and get the delta."""
        now = time.time()
        delta, self.last_time = now - self.last_time, now
        return delta

    def idle(self):
        """Log an idling cycle."""
        self.log("idling")

        now = time.time()
        if now - self.last_idle_print > IDLE_SPARK_DELAY:
            self.print_idle_report(now)

    def print_idle_report(self, now):
        self.idle_log.append(int(self.idle_time * 1000))
        if len(self.idle_log) > IDLE_LOG_CAP:
            self.idle_log = self.idle_log[len(self.idle_log) - IDLE_LOG_CAP:]
        print "Idle usage: %.2fs - %s" % (self.idle_time,
                                        spark_string(self.idle_log))

        # Atomically add in the new idle time and reset the tentative idle
        # counter.
        self.total_idle_time, self.idle_time = (self.total_idle_time +
                                                    self.idle_time, 0)
        self.last_idle_print = now

    def log(self, name):
        """
        Stop logging the last time tag and save it, then start logging a new
        time tag.
        """
        last_action = self.last_action
        if name == last_action:
            return

        if last_action == "idling":
            self.idle_time += self.reset_time()
        else:
            if last_action not in self.times:
                self.times[last_action] = 0
            self.times[last_action] += self.reset_time()

        if name is None:
            self.last_action = "profiling"
        else:
            self.last_action = name

    def print_report(self):
        """Print a report to stdout."""

        # Stop logging whatever we're logging now.
        self.log(None)

        idle_time = self.total_idle_time + self.idle_time

        ops = self.times.keys() + ["(idling)"]
        total = sum(self.times.values() + [idle_time])
        percents = [(key, val, val / total * 100) for
                    key, val in self.times.items()]
        percents = sorted(percents, key=lambda x: x[1])
        percents.reverse()

        # Format and print the report.
        longest_name = max(len(x) for x in ops)
        template = "%s | %s | %s"
        output = []

        def format(name, seconds, percent):
            if not isinstance(seconds, str):
                seconds = str(round(seconds, 2))
                percent = str(round(percent, 3)) + "%"
            output.append(template % (name.ljust(longest_name),
                                      seconds.ljust(7),
                                      percent))

        format("Operation", "Time", "Percent")
        output.append("-" * len(output[0]))
        format("(idling)", idle_time, idle_time / total * 100)
        for line in percents:
            format(*line)

        uptime = time.time() - self.start_time
        uptime_unit = "s"
        if uptime > 60:
            uptime, uptime_unit = uptime / 60, "min"
            if uptime > 60:
                uptime, uptime_unit = uptime / 60, "hours"
                if uptime > 24:
                    uptime, uptime_unit = uptime / 24, "days"

        print "\nUptime: %.2f%s" % (uptime, uptime_unit)
        print "\n".join(output)
        print "\n"

