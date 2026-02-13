import time

class SimulationClock:
    def __init__(self, time_scale=15.0, start_hour=6):
        # 1 real seconds = 15 simulated minutes, starting at 6:00 AM
        self.time_scale = time_scale
        self.start_time = time.time()
        self.start_hour = start_hour
        self.last_day_checked = -1

    def get_sim_time(self):
        elapsed_real_minutes = (time.time() - self.start_time) / 60.0
        elapsed_sim_minutes = elapsed_real_minutes * self.time_scale
        #total_minutes = int((self.start_hour * 60) + elapsed_sim_minutes)
        
        sim_days = int(elapsed_sim_minutes) // (24 * 60)     #minutes per day = 24*60
        remaining_minutes = int(elapsed_sim_minutes % (24 * 60))
        
        temp_hour = (remaining_minutes // 60) + self.start_hour
        sim_hours = temp_hour % 24
        sim_days += temp_hour // 24
        sim_minutes = remaining_minutes % 60
        total_minutes = int(elapsed_sim_minutes + (self.start_hour * 60))

        return sim_days, sim_hours, sim_minutes, total_minutes

    def get_time_string(self):
        days, hours, minutes, _ = self.get_sim_time()
        return f"Day {days}, {hours:02d}:{minutes:02d}"

    def is_new_day(self):
        days, _, _, _ = self.get_sim_time()
        if days > self.last_day_checked:
            self.last_day_checked = days
            return True
        return False
