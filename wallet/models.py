import calendar
import json
import datetime
from functools import wraps
from collections import OrderedDict

import requests
import arrow
from django.db import models
from django.core.cache import cache

from coinkit import (BitcoinKeypair, PeercoinKeypair, LitecoinKeypair,
    DogecoinKeypair,FeathercoinKeypair)

class CryptoWallet(models.Model):
    """
    Base methods for all types of cryptocurrency wallets
    """
    owner = models.ForeignKey('auth.User')
    date_created = models.DateTimeField(default=datetime.datetime.now)
    name = models.TextField(max_length=64, blank=True)
    public_key = models.TextField()
    private_key = models.TextField(null=True, blank=True)

    def __unicode__(self):
        return "%s - %s" % (self.owner.username, self.public_key)

    def has_private_key(self):
        return bool(self.private_key)

    def price_json(self, fiat_symbol='usd', hard_refresh=False):
        """
        Return a json encoded dict of price info. This data format is used for
        various things on the front end.
        """
        return json.dumps({
            'wallet_value': self.get_value(hard_refresh=hard_refresh),
            'fiat_exchange': self.get_fiat_exchange(fiat_symbol, hard_refresh=hard_refresh),
            'fiat_symbol': fiat_symbol.upper(),
            'crypto_symbol': self.symbol.upper(),
            'price_source': self.price_source,
        })

    def js_id(self):
        """
        This is how the front end (javascript) identifies wallets.
        """
        return "%s-%s" % (self.symbol.lower(), self.pk)

    def get_fiat_value(self, fiat='usd'):
        """
        Multiply a crypto amunt by the returned number to get the value of that
        crypto amount in local currency. For instance a bitcoin wallet with
        2.3 bitcoins can be converted to USD by:
        >>> btc = BitcoinWallet()
        >>> fiat_conversion = btc.get_fiat_value('usd')
        >>> 2.3 * fiat_conversion
        1894.4 # 2.3 bitcoins == 1894.4 USD
        """
        return self.get_value() * self.get_fiat_exchange(fiat)

    def get_value(self):
        """
        Get the total amount of currency units that this wallet holds.
        Get from the blockchain. Either through an external service or
        through a locally running *coind
        """
        raise NotImplementedError()

    def send_to_address(self, address, amount):
        """
        Create a transaction of passed in amount to passed in address and send
        off to the coin network. Done either through an external service
        or through locally ran *coind.
        """
        raise NotImplementedError()

    def get_transactions(self):
        """
        Make a call to an external service and get all transactions for this
        address.
        """
        raise NotImplementedError()

    @classmethod
    def get_historical_price(self, date, fiat_symbol='usd'):
        url = "http://coinsentry.pw/price_for_date?fiat=%s&crypto=%s&date=%s"
        url = url % (fiat_symbol, self.symbol, date.isoformat())
        response = requests.get(url)
        print url, response.content
        return response.json()

    @classmethod
    def get_fiat_exchange(cls, currency='usd'):
        """
        Return the amount of units of currency per USD.
        Returned as a float. Not all subclasses may implement
        every curency.
        """
        raise NotImplementedError()

    @classmethod
    def generate_new_keypair(cls):
        raise NotImplementedError()

    class Meta:
        abstract = True


def bypassable_cache(func):
    """
    Cache decorator that caches the output of the function, but allows for the
    ability to bypass the cache by pasing in the 'bypass_cache' kwarg to be true.
    Also you can pass in 'hard_refresh' that will never read from cache, but
    will write it's output to cache.
    """
    @wraps(func)
    def lil_wayne(*args, **kwargs):
        hard_refresh = kwargs.pop('hard_refresh', False)
        bypass_cache = kwargs.pop('bypass_cache', False)

        key = '%s%s%s' % (func.__name__, str(args), str(kwargs))
        key = key.replace(' ', '') # to avoid bug in memcached

        if bypass_cache:
            print "bypass", key
            return func(*args, **kwargs)

        if hard_refresh:
            ret = func(*args, **kwargs)
            cache.set(key, ret)
            print "hard refresh", key
            return ret

        hit = cache.get(key)
        if hit is not None:
            print "return hit", key
            return hit

        print "hitting because of a miss", key
        ret = func(*args, **kwargs)
        cache.set(key, ret)
        return ret
    return lil_wayne

class Transaction(object):
    """
    Like a model class, but not a django model because transactions are
    always sourced from external data sources. All cryptocurrencies will use this
    class for handling transactions.
    """
    crypto_symbol = 'btc'
    cardinal = '1' # first, second, third transaction for an address... expressed as int
    txid = '' # long hash that this tx is indexed by in the blockchain
    amount = 0.0 # positive float for recieved transaction, negative for send
    other_address = '' # either the sender or the recipient's public key/address
    confirmations = ''
    date = '' # date of transaction

    def historical_price(self, fiat_symbol):
        """
        Using the local cache, get the fiat price at the time of
        transaction.
        """
        return HistoricalPrice.get_value(
            self.date, self.crypto_symbol, fiat_symbol
        )


class BitcoinWallet(CryptoWallet):
    symbol = 'BTC'
    full_name = 'Bitcoin'
    price_source = 'coinbase.com'

    @bypassable_cache
    def get_value(self):
        url = "http://blockchain.info/address/%s?format=json"
        response = requests.get(url  % self.public_key)
        return float(response.json()['final_balance']) * 1e-8

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        if fiat_symbol != 'usd':
            raise NotImplementedError("USD for BTC only")
        response = requests.get("https://coinbase.com/api/v1/prices/spot_rate")
        return float(response.json()['amount'])

    @classmethod
    def generate_new_keypair(cls):
        keypair = BitcoinKeypair()
        return keypair.address(), keypair.private_key()

    def send_to_address(self, address, amount):
        """
        Make call to bitcoind through rpc.
        """
        raise NotImplementedError()

    @bypassable_cache
    def get_transactions(self):
        url = 'http://btc.blockr.io/api/v1/address/txs/' + self.public_key
        response = requests.get(url)
        txs = response.json()['data']['txs']
        transactions = []
        for tx in txs:
            t = Transaction()
            t.date = arrow.get(tx['time_utc']).datetime
            t.amount = tx['amount']
            t.crypto_symbol = 'btc'
            t.txid = tx['tx']
            t.confirmations = tx['confirmations']
            transactions.append(t)
        return transactions


class LitecoinWallet(CryptoWallet):
    symbol = "LTC"
    full_name = 'Litecoin'
    price_source = "btc-e"

    @bypassable_cache
    def get_value(self):
        url = "http://ltc.blockr.io/api/v1/address/balance/"
        response = requests.get(url + self.public_key)
        return float(response.json()['data']['balance'])

    def send_to_address(self, address, amount):
        raise NotImplementedError()

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        url = "https://btc-e.com/api/2/ltc_%s/ticker" % fiat_symbol
        response = requests.get(url)
        return float(response.json()['ticker']['avg'])

    @classmethod
    def generate_new_keypair(cls):
        keypair = LitecoinKeypair()
        return keypair.address(), keypair.private_key()

    @bypassable_cache
    def get_transactions(self):
        url = 'http://ltc.blockr.io/api/v1/address/txs/' + self.public_key
        response = requests.get(url)
        txs = response.json()['data']['txs']
        transactions = []
        for tx in txs:
            t = Transaction()
            t.date = arrow.get(tx['time_utc']).datetime
            t.amount = tx['amount']
            t.crypto_symbol = 'ltc'
            t.txid = tx['tx']
            t.confirmations = tx['confirmations']
            transactions.append(t)
        return transactions

class DogecoinWallet(CryptoWallet):
    symbol = "DOGE"
    full_name = 'Dogecoin'
    price_source = 'dogeapi.com'

    @bypassable_cache
    def get_value(self):
        url = "https://dogechain.info/chain/Dogecoin/q/addressbalance/"
        response = requests.get(url + self.public_key)
        return float(response.content)

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        url = "https://www.dogeapi.com/wow/v2/?a=get_current_price&convert_to=%s&amount_doge=1"
        response = requests.get(url % fiat_symbol.upper())
        return float(response.json()['data']['amount'])

    def send_to_address(self, address, amount):
        raise NotImplementedError()

    @classmethod
    def generate_new_keypair(cls):
        keypair = DogecoinKeypair()
        return keypair.address(), keypair.private_key()

    def get_transactions(self):
        """
        This is what gets returned and iterated over from chain.so
        [
            {
             u'script_hex': u'76a91425877fec61fa9f74592ccfc43cd7430862171fd588ac',
             u'script_asm': u'OP_DUP OP_HASH160 25877fec61fa9f74592ccfc43cd7430862171fd5 OP_EQUALVERIFY OP_CHECKSIG',
             u'value': u'98995.00000000',
             u'txid': u'b6bd31a9d4db7a6d54a64086a0a51432336fb18338bece3f8382faa79728fbfc',
             u'confirmations': 16424,
             u'time': 1402876124,
             u'output_no': 1
            }
        ]
        """
        url = "https://chain.so/api/v2/get_tx_unspent/DOGE/"
        response = requests.get(url + self.public_key)

        txs = response.json()['data']['txs']
        transactions = []
        for tx in txs:
            t = Transaction()
            t.date = arrow.get(tx['time']).datetime
            t.amount = tx['value']
            t.crypto_symbol = 'doge'
            t.txid = tx['txid']
            t.confirmations = tx['confirmations']
            transactions.append(t)
        return transactions


class PeercoinWallet(CryptoWallet):
    symbol = "PPC"
    full_name = 'Peercoin'
    price_source = 'btc-e'

    @bypassable_cache
    def get_value(self):
        url = "http://ppc.blockr.io/api/v1/address/balance/"
        response = requests.get(url + self.public_key)
        return float(response.json()['data']['balance'])

    def send_to_address(self, address, amount):
        raise NotImplementedError()

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        url="http://www.cryptocoincharts.info/v2/api/tradingPair/ppc_%s" % fiat_symbol
        response = requests.get(url)
        return float(response.json()['price'])

    @classmethod
    def generate_new_keypair(cls):
        keypair = PeercoinKeypair()
        return keypair.address(), keypair.private_key()

    @bypassable_cache
    def get_transactions(self):
        """
        [
            {
             u'time_utc': u'2014-06-16T00:07:10Z',
             u'amount': 103.98,
             u'confirmations': 2152,
             u'amount_multisig': 0,
             u'tx': u'6dddc4deb0806d987844b429e73b20ce5f0355407cce220130b5eac8fa13970e'
            }
        ]
        """
        url = 'http://ppc.blockr.io/api/v1/address/txs/' + self.public_key
        response = requests.get(url)
        txs = response.json()['data']['txs']
        import debug
        transactions = []
        for tx in txs:
            t = Transaction()
            t.date = arrow.get(tx['time_utc']).datetime
            t.amount = tx['amount']
            t.crypto_symbol = 'ppc'
            t.txid = tx['tx']
            t.confirmations = tx['confirmations']
            transactions.append(t)
        return transactions

class FeathercoinWallet(CryptoWallet):
    symbol = 'FTC'
    full_name = 'Feathercoin'
    price_source = 'api.feathercoin.com'

    @bypassable_cache
    def get_value(self):
        url= "http://api.feathercoin.com/?output=balance&address=%s&json=1" % self.public_key
        response = requests.get(url)
        try:
            return float(response.json()['balance'])
        except:
            return 0

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        fiat_symbol = fiat_symbol.lower()
        url="http://api.feathercoin.com/?output=%s&amount=1&json=1" % fiat_symbol
        response = requests.get(url)
        return float(response.json()[fiat_symbol])

    @classmethod
    def generate_new_keypair(cls):
        keypair = FeathercoinKeypair()
        return keypair.address(), keypair.private_key()


class VertcoinWallet(CryptoWallet):
    symbol = 'VTC'
    full_name = 'Vertcoin'
    price_source = 'cryptocoincharts.info'

    @bypassable_cache
    def get_value(self):
        url = "https://explorer.vertcoin.org/chain/Vertcoin/q/addressbalance/"
        response = requests.get(url + self.public_key)
        return float(response.content)

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        url="http://www.cryptocoincharts.info/v2/api/tradingPair/vtc_%s" % fiat_symbol
        response = requests.get(url)
        return float(response.json()['price'])


class NextWallet(CryptoWallet):
    symbol = 'NXT'
    full_name = 'Next'
    price_source = 'cryptocoincharts.info'

    @bypassable_cache
    def get_value(self):
        url='http://nxtportal.org/nxt?requestType=getAccount&account='
        response = requests.get(url + self.public_key)
        return float(response.json()['balanceNQT']) * 1e-8

    @classmethod
    @bypassable_cache
    def get_fiat_exchange(cls, fiat_symbol='usd'):
        url="http://www.cryptocoincharts.info/v2/api/tradingPair/nxt_%s" % fiat_symbol
        response = requests.get(url)
        return float(response.json()['price'])


wallet_classes = OrderedDict((
    ('btc', BitcoinWallet),
    ('ltc', LitecoinWallet),
    ('doge', DogecoinWallet),
    ('vtc', VertcoinWallet),
    ('ppc', PeercoinWallet),
    ('nxt', NextWallet),
    ('ftc', FeathercoinWallet),
))

class HistoricalPrice(models.Model):
    crypto_symbol = models.CharField(max_length=8)
    fiat_symbol = models.CharField(max_length=8)
    when = models.DateTimeField()
    price = models.FloatField()
    source = models.CharField(max_length=64)

    def __unicode__(self):
        return "{}:{:%d, %b %Y}:{}".format(self.source, self.when, self.price)

    @classmethod
    def fetch(cls, when, crypto_symbol='btc', fiat_symbol='usd'):
        """
        Get the appropriate Wallet model and call it's get_historical
        method. That method will then call an external data source.
        The results are then returned and stored for later use.
        """
        Wallet = wallet_classes[crypto_symbol]
        price, source = Wallet.get_historical_price(when, fiat_symbol=fiat_symbol)
        obj = cls.objects.create(
            fiat_symbol=fiat_symbol,
            crypto_symbol=crypto_symbol,
            when=when,
            source=source,
            price=price
        )
        return obj

    @classmethod
    def get_value(cls, when, crypto_symbol='btc', fiat_symbol='usd'):
        """
        This function is the primary interface to the historical price
        system. It first tries the database, if no match, it calls the
        correct external source (such as bitcoincharts.com).
        """
        d = datetime.timedelta(hours=1)
        historical_price = cls.objects.filter(
            crypto_symbol=crypto_symbol,
            fiat_symbol=fiat_symbol,
            when__range=[when-d, when+d]
        )
        try:
            obj = historical_price[0]
        except IndexError:
            obj = cls.fetch(when, crypto_symbol=crypto_symbol, fiat_symbol=fiat_symbol)

        return obj.price, obj.source
