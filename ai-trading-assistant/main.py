import asyncio
import logging
import os
import re
from typing import Dict, Any, List
from datetime import datetime
import pandas as pd
from enum import Enum, auto
import json

from components.config_manager import ConfigManager
from components.stock_scanner import StockScanner
from components.stock_analyzer import StockAnalyzer 
from components.trading_analyst import TradingAnalyst
from components.market_monitor import MarketMonitor
from components.output_formatter import OutputFormatter
from components.performance_tracker import PerformanceTracker
from components.robinhood_authenticator import RobinhoodAuthenticator
from components.position_manager import PositionManager

class TradingState(Enum):
    INITIALIZATION = auto()
    MARKET_SCANNING = auto()
    OPPORTUNITY_DETECTION = auto() 
    POSITION_MANAGEMENT = auto()
    EXIT_MANAGEMENT = auto()
    COOLDOWN = auto()

class TradingSystem:
    def __init__(self):
        self.current_state = TradingState.INITIALIZATION
        self._setup_logging()
        self._init_components()
        self.active_trades = {}
        self.metrics = {
            'trades_analyzed': 0,
            'setups_detected': 0,
            'trades_executed': 0,
            'successful_trades': 0,
            'daily_watchlist': []
        }

    def _setup_logging(self):
        os.makedirs('logs', exist_ok=True)
        handlers = []
        
        file_handler = logging.FileHandler('logs/trading_system.log')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'))
        handlers.append(file_handler)
        
        debug_handler = logging.FileHandler('logs/trading_system_debug.log')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'))
        handlers.append(debug_handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s'))
        handlers.append(console_handler)
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        for handler in handlers:
            root_logger.addHandler(handler)

    def _init_components(self):
        try:
            self.config_manager = ConfigManager('config.json')
            self.robinhood_auth = RobinhoodAuthenticator()
            self._check_robinhood_credentials()
            
            self.scanner = StockScanner()
            self.market_monitor = MarketMonitor()
            self.output_formatter = OutputFormatter()
            self.performance_tracker = PerformanceTracker()
            
            self.analyzer = StockAnalyzer(self.config_manager)
            self.position_manager = PositionManager(self.performance_tracker)
            self.trading_analyst = TradingAnalyst(
                performance_tracker=self.performance_tracker,
                position_manager=self.position_manager,
                model=self.config_manager.get('llm_configuration.model', 'llama3:latest')
            )
            
            logging.info("All components initialized successfully")
            
        except Exception as e:
            logging.error(f"Failed to initialize components: {str(e)}")
            raise

    def _check_robinhood_credentials(self):
        try:
            credentials = self.robinhood_auth.load_credentials()
            if not credentials:
                print("\n🤖 Robinhood Integration")
                choice = input("Configure Robinhood? (Y/N): ").strip().lower()
                if choice == 'y':
                    if not self.robinhood_auth.save_credentials():
                        raise Exception("Failed to save credentials")
                else:
                    logging.info("Running in analysis-only mode")
        except Exception as e:
            logging.error(f"Auth error: {str(e)}")
            print("Error setting up Robinhood. Running in analysis-only mode.")

    async def analyze_symbol(self, symbol: str):
        try:
            self.metrics['trades_analyzed'] += 1
            
            stock_data = self.analyzer.analyze_stock(symbol)
            if not stock_data:
                return

            technical_data = stock_data.get('technical_indicators', {})
            logging.info(f"Technical data for {symbol}:")
            logging.info(f"  Price: ${stock_data.get('current_price', 0):.2f}")
            logging.info(f"  RSI: {technical_data.get('rsi', 'N/A')}")
            logging.info(f"  VWAP: ${technical_data.get('vwap', 'N/A')}")
            
            open_positions = self.performance_tracker.get_open_positions()
            if not open_positions.empty and symbol in open_positions['symbol'].values:
                position = open_positions[open_positions['symbol'] == symbol].iloc[0]
                
                await self.trading_analyst.analyze_position(
                    stock_data=stock_data,
                    position_data={
                        'entry_price': position['entry_price'],
                        'current_price': stock_data['current_price'],
                        'target_price': position['target_price'],
                        'stop_price': position['stop_price'],
                        'size': position['position_size'],
                        'time_held': (datetime.now() - pd.to_datetime(position['timestamp'])).total_seconds() / 3600
                    }
                )
                return

            # Only analyze for new setups during regular market hours unless in testing mode
            market_phase = self.market_monitor.get_market_phase()
            if market_phase != 'regular' and not self.config_manager.get('testing_mode.enabled', False):
                return

            trading_setup = await self.trading_analyst.analyze_setup(stock_data)
            
            if trading_setup and 'NO SETUP' not in trading_setup:
                self.metrics['setups_detected'] += 1
                setup_details = self._parse_trading_setup(trading_setup)
                
                if setup_details:
                    formatted_setup = self.output_formatter.format_trading_setup(trading_setup)
                    print(formatted_setup)
                    
                    trade_data = {
                        'symbol': setup_details.get('symbol', symbol),
                        'entry_price': setup_details.get('entry', setup_details.get('entry_price')),
                        'target_price': setup_details.get('target', setup_details.get('target_price')),
                        'stop_price': setup_details.get('stop', setup_details.get('stop_price')),
                        'size': setup_details.get('size', 100),
                        'confidence': setup_details.get('confidence'),
                        'reason': setup_details.get('reason', ''),
                        'type': 'PAPER',
                        'status': 'OPEN',
                        'notes': 'Auto-generated by AI analysis'
                    }
                    
                    if self.performance_tracker.log_trade(trade_data):
                        self.metrics['trades_executed'] += 1
                        await self._execute_trade(symbol, setup_details)
                        
        except Exception as e:
            logging.error(f"Symbol analysis error: {str(e)}")

    async def _analyze_premarket_movers(self, symbols: List[str]):
        """Analyze pre-market movers and prepare watchlist"""
        try:
            premarket_movers = []
            for symbol in symbols:
                stock_data = self.analyzer.analyze_stock(symbol)
                if not stock_data:
                    continue
                    
                # Calculate pre-market change
                current_price = stock_data['current_price']
                prev_close = stock_data.get('previous_close', current_price)
                change_pct = ((current_price - prev_close) / prev_close) * 100
                volume = stock_data.get('volume_analysis', {}).get('current_volume', 0)
                avg_volume = stock_data.get('volume_analysis', {}).get('avg_volume', 1)
                rel_volume = volume / avg_volume if avg_volume > 0 else 0
                
                # Track significant pre-market activity
                if abs(change_pct) >= 3.0 or rel_volume >= 2.0:
                    premarket_movers.append({
                        'symbol': symbol,
                        'price': current_price,
                        'change_pct': change_pct,
                        'volume': volume,
                        'rel_volume': rel_volume,
                        'technical_indicators': stock_data.get('technical_indicators', {})
                    })
            
            if premarket_movers:
                logging.info("\nPre-market Movers:")
                for mover in sorted(premarket_movers, key=lambda x: abs(x['change_pct']), reverse=True):
                    logging.info(
                        f"{mover['symbol']}: {mover['change_pct']:+.1f}% | "
                        f"${mover['price']:.2f} | {mover['rel_volume']:.1f}x Volume"
                    )
                
                # Update watchlist for regular session
                self.metrics['daily_watchlist'] = [m['symbol'] for m in premarket_movers]
        
        except Exception as e:
            logging.error(f"Pre-market analysis error: {str(e)}")

    async def _generate_eod_report(self):
        """Generate end-of-day analysis and watchlist"""
        try:
            # Get today's performance
            report = self.performance_tracker.generate_report(days=1)
            logging.info(f"\nEnd of Day Report:\n{report}")
            
            # Analyze closed positions
            closed_positions = self.performance_tracker.get_trade_history(days=1)
            if not closed_positions.empty:
                win_rate = (closed_positions['profit_loss'] > 0).mean() * 100
                total_pl = closed_positions['profit_loss'].sum()
                avg_hold_time = closed_positions['time_held'].mean() if 'time_held' in closed_positions else 0
                
                logging.info(f"\nToday's Trading Summary:")
                logging.info(f"Win Rate: {win_rate:.1f}%")
                logging.info(f"Total P&L: ${total_pl:.2f}")
                logging.info(f"Average Hold Time: {avg_hold_time:.1f} hours")
                logging.info(f"Total Trades: {len(closed_positions)}")
            
            # Prepare for next session
            self.metrics.update({
                'trades_analyzed': 0,
                'setups_detected': 0,
                'trades_executed': 0,
                'successful_trades': 0,
                'daily_watchlist': []
            })
            
            # Clear caches
            self.analyzer.clear_cache()
            self.scanner.clear_cache()
            
        except Exception as e:
            logging.error(f"EOD report error: {str(e)}")

    async def run(self):
        while True:
            try:
                await self._update_state(TradingState.INITIALIZATION)
                
                market_phase = self.market_monitor.get_market_phase()
                
                if market_phase == 'closed':
                    logging.info("Market closed. Waiting for next session...")
                    await asyncio.sleep(300)  # Check every 5 minutes
                    continue
                    
                elif market_phase == 'pre-market':
                    logging.info("Pre-market session. Running pre-market scan...")
                    # Reduced scanning frequency, focus on gap analysis
                    symbols = await self.scanner.get_symbols(max_symbols=50)
                    await self._analyze_premarket_movers(symbols)
                    await asyncio.sleep(300)  # 5-minute delay between pre-market scans
                    continue
                    
                elif market_phase == 'post-market':
                    logging.info("Post-market session. Generating end-of-day report...")
                    await self._generate_eod_report()
                    await asyncio.sleep(300)  # 5-minute delay between post-market checks
                    continue
                
                # Regular market hours processing
                await self._update_state(TradingState.MARKET_SCANNING)
                
                symbols = await self.scanner.get_symbols(
                    max_symbols=self.config_manager.get('system_settings.max_symbols', 100)
                )
                
                # Add symbols from daily watchlist
                watchlist_symbols = [s for s in self.metrics['daily_watchlist'] if s not in symbols]
                symbols.extend(watchlist_symbols)
                
                # Add symbols from open positions
                open_positions = self.performance_tracker.get_open_positions()
                active_symbols = open_positions['symbol'].tolist()
                symbols.extend([s for s in active_symbols if s not in symbols])
                
                logging.info(f"Analyzing {len(symbols)} symbols "
                           f"({len(active_symbols)} active, {len(watchlist_symbols)} watchlist)")
                
                if not symbols:
                    await asyncio.sleep(60)
                    continue
                
                await self._update_state(TradingState.OPPORTUNITY_DETECTION)
                
                tasks = [self.analyze_symbol(symbol) for symbol in symbols]
                
                try:
                    await asyncio.gather(*tasks)
                except Exception as e:
                    logging.error(f"Error during symbol analysis: {str(e)}")
                
                await self._update_state(TradingState.COOLDOWN)
                
                scan_interval = self.config_manager.get('system_settings.scan_interval', 60)
                await asyncio.sleep(scan_interval)
            
            except Exception as e:
                logging.error(f"Main loop error: {str(e)}")
                await asyncio.sleep(60)
