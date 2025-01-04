import asyncio
import logging
import json
import os
from datetime import datetime
from enum import Enum, auto
from typing import Dict, List, Optional, Any

# Import components
from components.config_manager import ConfigManager
from components.stock_scanner import StockScanner
from components.stock_analyzer import StockAnalyzer
from components.trading_analyst import TradingAnalyst
from components.market_monitor import MarketMonitor
from components.output_formatter import OutputFormatter
from components.performance_tracker import PerformanceTracker
from components.robinhood_authenticator import RobinhoodAuthenticator

class TradingState(Enum):
    """Trading system state enumeration"""
    INITIALIZATION = auto()
    MARKET_SCANNING = auto()
    OPPORTUNITY_DETECTION = auto()
    ENTRY_DECISION = auto()
    ACTIVE_MONITORING = auto()
    EXIT_MANAGEMENT = auto()
    COOLDOWN = auto()

class TradingSystem:
    def __init__(self):
        """Initialize Trading System with enhanced state management"""
        # Current state
        self.current_state = TradingState.INITIALIZATION
        
        # Setup logging with enhanced format
        self._setup_logging()
        
        # System components initialization
        self._init_components()
        
        # Active trades tracking
        self.active_trades: Dict[str, Dict[str, Any]] = {}
        
        # Performance metrics
        self.metrics = {
            'trades_analyzed': 0,
            'setups_detected': 0,
            'trades_executed': 0,
            'successful_trades': 0
        }

    def _init_components(self):
        """Initialize system components with proper error handling"""
        try:
            # Load configuration
            self.config_manager = ConfigManager('config.json')
            
            # Initialize Robinhood authentication
            self.robinhood_auth = RobinhoodAuthenticator()
            
            # Check for Robinhood credentials
            self._check_robinhood_credentials()
            
            # Initialize other components
            self.scanner = StockScanner()
            self.market_monitor = MarketMonitor()
            self.output_formatter = OutputFormatter()
            self.performance_tracker = PerformanceTracker()
            
            # Initialize analyzer and trader with config
            self.analyzer = StockAnalyzer(self.config_manager)
            self.trading_analyst = TradingAnalyst()
            
            logging.info("All components initialized successfully")
            
        except Exception as e:
            logging.error(f"Failed to initialize components: {str(e)}")
            raise

    def _setup_logging(self):
        """Configure enhanced logging system"""
        try:
            # Create logs directory if it doesn't exist
            os.makedirs('logs', exist_ok=True)
            
            # Create separate log files for different severity levels
            handlers = [
                logging.FileHandler(f'logs/trading_system_{level.lower()}.log')
                for level in ['DEBUG', 'INFO', 'ERROR']
            ]
            
            # Add console handler
            handlers.append(logging.StreamHandler())
            
            # Configure logging with enhanced format
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s',
                handlers=handlers
            )
            
        except Exception as e:
            print(f"Failed to setup logging: {str(e)}")
            raise

    def _check_robinhood_credentials(self):
        """Verify and manage Robinhood authentication"""
        try:
            credentials = self.robinhood_auth.load_credentials()
            
            if not credentials:
                print("\n🤖 Robinhood Integration Setup")
                print("No credentials found. Would you like to configure Robinhood integration?")
                choice = input("(Y/N): ").strip().lower()
                
                if choice == 'y':
                    if not self.robinhood_auth.save_credentials():
                        raise Exception("Failed to save Robinhood credentials")
                else:
                    logging.info("Skipping Robinhood integration. Running in analysis-only mode.")
            
        except Exception as e:
            logging.error(f"Robinhood authentication error: {str(e)}")
            print("Error setting up Robinhood integration. Running in analysis-only mode.")

    async def _update_state(self, new_state: TradingState):
        """
        Update system state with logging and validation
        
        Args:
            new_state (TradingState): New state to transition to
        """
        old_state = self.current_state
        self.current_state = new_state
        
        logging.info(f"State transition: {old_state.name} -> {new_state.name}")
        
        # Perform state-specific initialization
        if new_state == TradingState.MARKET_SCANNING:
            await self._validate_market_conditions()
        elif new_state == TradingState.COOLDOWN:
            await self._perform_cooldown_tasks()

    async def _validate_market_conditions(self):
        """Validate current market conditions"""
        try:
            market_status = self.market_monitor.get_market_status()
            
            if not market_status['is_open']:
                time_until_open = market_status['time_until_open']
                logging.info(f"Market closed. Next session in {time_until_open}")
                
                # Sleep until market opens
                await asyncio.sleep(min(time_until_open.seconds, 3600))
                return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error validating market conditions: {str(e)}")
            return False

    async def _perform_cooldown_tasks(self):
        """Execute post-trade analysis and system maintenance"""
        try:
            # Generate performance report
            report = self.performance_tracker.generate_report()
            logging.info(f"Performance Report:\n{report}")
            
            # Update metrics
            self._update_performance_metrics()
            
            # Clean up any stale data
            self.active_trades.clear()
            
            # Brief cooldown period
            await asyncio.sleep(30)
            
        except Exception as e:
            logging.error(f"Error in cooldown tasks: {str(e)}")

    def _update_performance_metrics(self):
        """Update system performance metrics"""
        try:
            # Calculate success rate
            if self.metrics['trades_executed'] > 0:
                success_rate = (
                    self.metrics['successful_trades'] / 
                    self.metrics['trades_executed'] * 100
                )
                logging.info(f"Current success rate: {success_rate:.2f}%")
            
            # Log other metrics
            logging.info("Performance Metrics:")
            for metric, value in self.metrics.items():
                logging.info(f"- {metric}: {value}")
                
        except Exception as e:
            logging.error(f"Error updating metrics: {str(e)}")

    async def analyze_symbol(self, symbol: str):
        """
        Analyze a single stock symbol with enhanced error handling and logging
        
        Args:
            symbol (str): Stock ticker symbol
        """
        try:
            self.metrics['trades_analyzed'] += 1
            
            # Analyze stock data
            stock_data = self.analyzer.analyze_stock(symbol)
            
            if not stock_data:
                logging.debug(f"No analyzable data for {symbol}")
                return
            
            # Get trading setup from AI
            trading_setup = await self.trading_analyst.analyze_setup(stock_data)
            
            # Process valid setup
            if trading_setup and 'NO SETUP' not in trading_setup:
                self.metrics['setups_detected'] += 1
                
                # Format and display setup
                formatted_setup = self.output_formatter.format_trading_setup(trading_setup)
                print(formatted_setup)
                
                # Extract setup details
                setup_details = self._parse_trading_setup(trading_setup)
                
                # Log trade setup
                self.performance_tracker.log_trade(
                    symbol=symbol,
                    entry_price=setup_details['entry_price'],
                    confidence=setup_details['confidence'],
                    setup_details=trading_setup
                )
                
                # Execute trade if conditions met
                await self._execute_trade(symbol, setup_details)
        
        except Exception as e:
            logging.error(f"Error analyzing {symbol}: {str(e)}")

    def _parse_trading_setup(self, setup: str) -> Dict[str, Any]:
        """
        Parse trading setup string into structured data
        
        Args:
            setup (str): Trading setup string
        
        Returns:
            dict: Parsed setup details
        """
        try:
            # Extract key components using string parsing
            lines = setup.split('\n')
            
            return {
                'entry_price': float(lines[1].split('$')[1]),
                'target_price': float(lines[2].split('$')[1]),
                'stop_price': float(lines[3].split('$')[1]),
                'size': int(lines[4].split(':')[1].strip().split()[0]),
                'confidence': float(lines[6].split(':')[1].strip().rstrip('%'))
            }
            
        except Exception as e:
            logging.error(f"Error parsing trading setup: {str(e)}")
            return {}

    async def _execute_trade(self, symbol: str, setup: Dict[str, Any]):
        """
        Execute trade based on setup details
        
        Args:
            symbol (str): Stock symbol
            setup (dict): Trading setup details
        """
        try:
            # Check for Robinhood credentials
            credentials = self.robinhood_auth.load_credentials()
            if not credentials:
                return

            # Validate confidence threshold
            if setup['confidence'] <= 80:
                logging.info(f"Setup confidence {setup['confidence']}% below threshold for {symbol}")
                return

            self.metrics['trades_executed'] += 1
            
            # Add to active trades
            self.active_trades[symbol] = {
                'entry_price': setup['entry_price'],
                'target_price': setup['target_price'],
                'stop_price': setup['stop_price'],
                'size': setup['size'],
                'entry_time': datetime.now()
            }
            
            # Log trade execution
            logging.info(f"Executing trade for {symbol}:")
            for key, value in setup.items():
                logging.info(f"- {key}: {value}")
            
            # TODO: Add actual Robinhood trade execution
            # This would use robin-stocks library
            
        except Exception as e:
            logging.error(f"Error executing trade: {str(e)}")

    async def run(self):
        """Main trading system loop with enhanced state management"""
        while True:
            try:
                # Start in initialization state
                await self._update_state(TradingState.INITIALIZATION)
                
                # Validate market conditions
                if not await self._validate_market_conditions():
                    continue
                
                # Update state to market scanning
                await self._update_state(TradingState.MARKET_SCANNING)
                
                # Get symbols to analyze
                symbols = self.scanner.get_symbols()
                logging.info(f"Found {len(symbols)} symbols to analyze")
                
                # Update state to opportunity detection
                await self._update_state(TradingState.OPPORTUNITY_DETECTION)
                
                # Create analysis tasks
                tasks = [self.analyze_symbol(symbol) for symbol in symbols]
                
                # Run analysis concurrently
                await asyncio.gather(*tasks)
                
                # Move to cooldown state
                await self._update_state(TradingState.COOLDOWN)
                
                # Configure scan interval
                scan_interval = self.config_manager.get('scan_interval', 60)
                await asyncio.sleep(scan_interval)
            
            except Exception as e:
                logging.error(f"Main loop error: {str(e)}")
                await asyncio.sleep(60)  # Error cooldown

def main():
    """Entry point with enhanced error handling"""
    try:
        # Create trading system
        trading_system = TradingSystem()
        
        # Run the async main loop
        asyncio.run(trading_system.run())
    
    except KeyboardInterrupt:
        print("\nTrading system stopped by user.")
        logging.info("Trading system shutdown initiated by user")
    
    except Exception as e:
        logging.critical(f"Fatal error in trading system: {str(e)}")
        raise
    
    finally:
        logging.info("Trading system shutdown complete")

if __name__ == "__main__":
    main()
