import time

class SimulationClock:
    def __init__(self, time_scale=15.0, start_hour=6):
        """
        time_scale: How many simulation minutes pass in one real minute. Default is 15 (1 real min = 15 sim mins).
        start_hour: The hour the simulation starts at (0-23).
        """
        self.time_scale = time_scale
        self.start_time = time.time()
        self.start_hour = start_hour
        self.last_day_checked = -1

    def get_total_sim_minutes(self):
        elapsed_real_seconds = time.time() - self.start_time
        elapsed_sim_minutes = (elapsed_real_seconds / 60.0) * self.time_scale
        return (self.start_hour * 60) + elapsed_sim_minutes

    def get_sim_time(self):
        total_minutes = self.get_total_sim_minutes()
        
        sim_days = int(total_minutes // (24 * 60))
        remaining_minutes = total_minutes % (24 * 60)
        
        sim_hours = int(remaining_minutes // 60)
        sim_minutes = int(remaining_minutes % 60)
        
        return sim_days, sim_hours, sim_minutes

    def get_time_string(self):
        days, hours, minutes = self.get_sim_time()
        return f"Day {days}, {hours:02d}:{minutes:02d}"

    def is_new_day(self):
        days, _, _ = self.get_sim_time()
        if days > self.last_day_checked:
            self.last_day_checked = days
            return True
        return False
