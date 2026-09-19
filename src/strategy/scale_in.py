import yaml

class ScaleInEngine:
    def __init__(self, ticker, config_path="config/strategy.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.ticker = ticker
        self.tiers = self.config['strategy']['scale_in'].get(ticker, {}).get('tiers', [])
        self.state = 'FLAT'
        self.last_z_atr = 0

    def get_action(self, d_atr, regime, is_panic):
        if regime == 'BEAR' or is_panic:
            return 'HOLD', self.state
            
        if self.state == 'FLAT':
            # Check T1
            t1 = next((t for t in self.tiers if t['name'] == 'T1'), None)
            if t1 and d_atr <= t1['z_atr']:
                self.state = 'T1_ACTIVE'
                self.last_z_atr = d_atr
                return 'BUY_T1', self.state
        
        elif self.state == 'T1_ACTIVE':
            t2 = next((t for t in self.tiers if t['name'] == 'T2'), None)
            if t2 and d_atr <= t2['z_atr'] and d_atr < self.last_z_atr:
                self.state = 'T2_ACTIVE'
                self.last_z_atr = d_atr
                return 'BUY_T2', self.state
                
        elif self.state == 'T2_ACTIVE':
            t3 = next((t for t in self.tiers if t['name'] == 'T3'), None)
            if t3 and d_atr <= t3['z_atr'] and d_atr < self.last_z_atr:
                self.state = 'T3_ACTIVE'
                self.last_z_atr = d_atr
                return 'BUY_T3', self.state
        
        return 'HOLD', self.state
