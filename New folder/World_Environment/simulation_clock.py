import time

class SimulationClock:
    def __init__(self, time_scale=6.0, start_hour=6):
        # 1 real seconds = 6 simulated minutes, starting at 6:00
        self.time_scale = time_scale
        self.start_time = time.time()
        self.start_hour = start_hour
        self.last_checked_day = -1

    def get_sim_time(self):
        elapsed_real_minutes = (time.time() - self.start_time) / 60.0
        elapsed_sim_minutes = elapsed_real_minutes * self.time_scale
        total_sim_minutes = int((self.start_hour * 60) + elapsed_sim_minutes)
        
        sim_days = total_sim_minutes // (24 * 60)
        sim_hours = (total_sim_minutes % (24 * 60)) // 60
        sim_minutes = total_sim_minutes % 60

        return sim_days, sim_hours, sim_minutes, total_sim_minutes

    def get_sim_hour(self):
        _, sim_hours, _, _ = self.get_sim_time()
        return sim_hours
    
    def get_sim_days(self):
        days, _, _, _ = self.get_sim_time()
        return days

    def get_time_string(self):
        days, hours, minutes, _ = self.get_sim_time()
        return f"Day {days}, {hours:02d}:{minutes:02d}"

    def is_new_day(self):
        current_day = self.get_sim_days()
        if current_day > self.last_checked_day:
            self.last_checked_day = current_day
            return True
        return False
        
    def update_world_time(self, state_manager, lock):
        with lock:
            state_manager.set_time(self.get_time_string())
