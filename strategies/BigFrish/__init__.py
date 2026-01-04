from jesse.strategies import Strategy
import jesse.indicators as ta
from jesse import utils
import requests
from typing import Union


class VolumeEMAStrategy(Strategy):
    """
    Stratégie basée sur Volume + EMA1440 avec filtres avancés
    Notifications Telegram intégrées
    """
    
    def __init__(self):
        super().__init__()
        self.telegram_sent = False
        
    # ========== PARAMÈTRES DE BASE ==========
    def hyperparameters(self):
        return [
            # EMA et Volume
            {'name': 'ema_volume_length', 'type': int, 'min': 1000, 'max': 2000, 'default': 1400},
            {'name': 'volume_multiplier', 'type': float, 'min': 5.0, 'max': 20.0, 'default': 10.0},
            {'name': 'ema_price_trend', 'type': int, 'min': 1000, 'max': 2000, 'default': 1440},
            
            # Filtres Volume Avancés
            {'name': 'use_volume_growth', 'type': bool, 'default': True},
            {'name': 'min_growth_percent', 'type': float, 'min': 5.0, 'max': 30.0, 'default': 15.0},
            {'name': 'growth_lookback', 'type': int, 'min': 2, 'max': 10, 'default': 5},
            
            {'name': 'use_sustained_volume', 'type': bool, 'default': True},
            {'name': 'min_consecutive_bars', 'type': int, 'min': 1, 'max': 5, 'default': 2},
            
            {'name': 'use_volume_rsi', 'type': bool, 'default': True},
            {'name': 'min_volume_rsi', 'type': int, 'min': 40, 'max': 70, 'default': 55},
            
            # Risk Management
            {'name': 'tp_percent', 'type': float, 'min': 1.0, 'max': 10.0, 'default': 4.0},
            {'name': 'sl_percent', 'type': float, 'min': 0.5, 'max': 5.0, 'default': 2.0},
            {'name': 'use_trailing_stop', 'type': bool, 'default': True},
            {'name': 'trail_activation', 'type': float, 'min': 1.0, 'max': 5.0, 'default': 2.0},
            {'name': 'trail_offset', 'type': float, 'min': 0.5, 'max': 3.0, 'default': 1.0},
            {'name': 'use_ema_sl', 'type': bool, 'default': True},
            
            # Telegram
            {'name': 'telegram_token', 'type': str, 'default': ''},
            {'name': 'telegram_chat_id', 'type': str, 'default': ''},
        ]
    
    # ========== INDICATEURS ==========
    @property
    def ema_volume(self):
        """EMA du volume"""
        return ta.ema(self.candles[:, 5], self.hp['ema_volume_length'])
    
    @property
    def ema_trend(self):
        """EMA de tendance sur le prix"""
        return ta.ema(self.candles[:, 2], self.hp['ema_price_trend'])
    
    @property
    def volume_rsi(self):
        """RSI calculé sur le volume"""
        return ta.rsi(self.candles[:, 5], 14)
    
    @property
    def current_volume(self):
        """Volume actuel"""
        return self.candles[-1, 5]
    
    @property
    def ema_volume_growth(self):
        """Croissance de l'EMA Volume en %"""
        lookback = self.hp['growth_lookback']
        if len(self.ema_volume) < lookback + 1:
            return 0
        current_ema = self.ema_volume[-1]
        past_ema = self.ema_volume[-lookback-1]
        if past_ema == 0:
            return 0
        return ((current_ema - past_ema) / past_ema) * 100
    
    @property
    def consecutive_volume_bars(self):
        """Nombre de bougies consécutives avec volume > EMA"""
        count = 0
        for i in range(len(self.candles)-1, -1, -1):
            if self.candles[i, 5] > self.ema_volume[i]:
                count += 1
            else:
                break
        return count
    
    # ========== FILTRES VOLUME ==========
    def check_volume_growth(self) -> bool:
        """Vérifie la croissance de l'EMA Volume"""
        if not self.hp['use_volume_growth']:
            return True
        return self.ema_volume_growth >= self.hp['min_growth_percent']
    
    def check_sustained_volume(self) -> bool:
        """Vérifie si le volume est soutenu"""
        if not self.hp['use_sustained_volume']:
            return True
        return self.consecutive_volume_bars >= self.hp['min_consecutive_bars']
    
    def check_volume_rsi_filter(self) -> bool:
        """Vérifie le RSI du volume"""
        if not self.hp['use_volume_rsi']:
            return True
        return self.volume_rsi[-1] >= self.hp['min_volume_rsi']
    
    def volume_spike(self) -> bool:
        """Détecte un pic de volume"""
        return self.current_volume > (self.ema_volume[-1] * self.hp['volume_multiplier'])
    
    # ========== CONDITIONS D'ENTRÉE ==========
    def should_long(self) -> bool:
        """Conditions pour LONG"""
        # Bougie haussière
        is_bullish = self.close > self.open
        
        # Prix au-dessus de la tendance
        above_trend = self.close > self.ema_trend[-1]
        
        # Pic de volume
        volume_ok = self.volume_spike()
        
        # Filtres volume avancés
        growth_ok = self.check_volume_growth()
        sustained_ok = self.check_sustained_volume()
        rsi_ok = self.check_volume_rsi_filter()
        
        return (is_bullish and above_trend and volume_ok and 
                growth_ok and sustained_ok and rsi_ok)
    
    def should_short(self) -> bool:
        """Conditions pour SHORT"""
        # Bougie baissière
        is_bearish = self.close < self.open
        
        # Prix en-dessous de la tendance
        below_trend = self.close < self.ema_trend[-1]
        
        # Pic de volume
        volume_ok = self.volume_spike()
        
        # Filtres volume avancés
        growth_ok = self.check_volume_growth()
        sustained_ok = self.check_sustained_volume()
        rsi_ok = self.check_volume_rsi_filter()
        
        return (is_bearish and below_trend and volume_ok and 
                growth_ok and sustained_ok and rsi_ok)
    
    def should_cancel_entry(self) -> bool:
        return False
    
    # ========== GESTION DES POSITIONS ==========
    def go_long(self):
        """Ouverture position LONG"""
        qty = self.position_size
        
        # Take Profit
        tp = self.price + (self.price * self.hp['tp_percent'] / 100)
        
        # Stop Loss
        if self.hp['use_ema_sl']:
            sl = self.ema_trend[-1]
        else:
            sl = self.price - (self.price * self.hp['sl_percent'] / 100)
        
        self.buy = qty, self.price
        self.take_profit = qty, tp
        self.stop_loss = qty, sl
        
        # Notification Telegram
        self.send_telegram_notification('LONG', tp, sl)
    
    def go_short(self):
        """Ouverture position SHORT"""
        qty = self.position_size
        
        # Take Profit
        tp = self.price - (self.price * self.hp['tp_percent'] / 100)
        
        # Stop Loss
        if self.hp['use_ema_sl']:
            sl = self.ema_trend[-1]
        else:
            sl = self.price + (self.price * self.hp['sl_percent'] / 100)
        
        self.sell = qty, self.price
        self.take_profit = qty, tp
        self.stop_loss = qty, sl
        
        # Notification Telegram
        self.send_telegram_notification('SHORT', tp, sl)
    
    def update_position(self):
        """Mise à jour trailing stop"""
        if not self.hp['use_trailing_stop']:
            return
        
        if self.is_long:
            # Activation du trailing stop
            activation_price = self.position.entry_price * (1 + self.hp['trail_activation'] / 100)
            
            if self.price >= activation_price:
                # Calcul nouveau stop loss
                new_sl = self.price * (1 - self.hp['trail_offset'] / 100)
                
                # Mise à jour si meilleur que l'actuel
                if new_sl > self.stop_loss[0][1]:
                    self.stop_loss = self.position.qty, new_sl
        
        elif self.is_short:
            # Activation du trailing stop
            activation_price = self.position.entry_price * (1 - self.hp['trail_activation'] / 100)
            
            if self.price <= activation_price:
                # Calcul nouveau stop loss
                new_sl = self.price * (1 + self.hp['trail_offset'] / 100)
                
                # Mise à jour si meilleur que l'actuel
                if new_sl < self.stop_loss[0][1]:
                    self.stop_loss = self.position.qty, new_sl
    
    # ========== TELEGRAM NOTIFICATION ==========
    def send_telegram_notification(self, side: str, tp: float, sl: float):
        """Envoie une notification sur Telegram"""
        token = self.hp['telegram_token']
        chat_id = self.hp['telegram_chat_id']
        
        if not token or not chat_id:
            return
        
        # Message formaté
        message = f"""
🚀 SIGNAL {side} - {self.symbol}

💰 Prix d'entrée: {self.price:.8f}
🎯 Take Profit: {tp:.8f} (+{self.hp['tp_percent']}%)
🛡 Stop Loss: {sl:.8f} (-{self.hp['sl_percent']}%)

📊 Volume: {self.current_volume:.0f}
📈 EMA Vol: {self.ema_volume[-1]:.0f}
🔥 Multiplier: {self.current_volume/self.ema_volume[-1]:.2f}x

📉 Croissance EMA Vol: {self.ema_volume_growth:.2f}%
📊 RSI Volume: {self.volume_rsi[-1]:.1f}
🔄 Bougies consécutives: {self.consecutive_volume_bars}

⏰ {utils.timestamp_to_time(self.current_candle[0])}
        """
        
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            print(f"Erreur Telegram: {e}")
    
    # ========== MÉTHODES ADDITIONNELLES ==========
    @property
    def position_size(self) -> float:
        """Calcul de la taille de position"""
        # Utilise tout le capital disponible
        return utils.size_to_qty(
            self.available_margin,
            self.price,
            fee_rate=self.fee_rate
        )
    
    def on_open_position(self, order):
        """Callback à l'ouverture de position"""
        self.telegram_sent = False
    
    def on_close_position(self, order):
        """Callback à la fermeture de position"""
        if not self.hp['telegram_token'] or not self.hp['telegram_chat_id']:
            return
        
        pnl = self.position.pnl
        pnl_percentage = self.position.pnl_percentage
        
        message = f"""
✅ POSITION FERMÉE - {self.symbol}

💵 PnL: {pnl:.2f} USD ({pnl_percentage:.2f}%)
📊 Prix de sortie: {self.price:.8f}
⏰ {utils.timestamp_to_time(self.current_candle[0])}
        """
        
        try:
            url = f"https://api.telegram.org/bot{self.hp['telegram_token']}/sendMessage"
            data = {
                "chat_id": self.hp['telegram_chat_id'],
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            print(f"Erreur Telegram: {e}")