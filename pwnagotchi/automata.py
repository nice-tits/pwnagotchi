import logging

import pwnagotchi.plugins as plugins
from pwnagotchi.ai.epoch import Epoch


# basic mood system
class Automata(object):
    def __init__(self, config, view):
        self._config = config
        self._view = view
        self._epoch = Epoch(config)

    def _on_miss(self, who):
        logging.info("it looks like %s is not in range anymore :/" % who)
        self._epoch.track(miss=True)
        self._view.on_miss(who)

    def _on_error(self, who, e):
        error = "%s" % e
        # when we're trying to associate or deauth something that is not in range anymore
        # (if we are moving), we get the following error from bettercap:
        # error 400: 50:c7:bf:2e:d3:37 is an unknown BSSID or it is in the association skip list.
        if 'is an unknown BSSID' in error:
            self._on_miss(who)
        else:
            logging.error("%s" % e)

    def set_starting(self):
        self._view.on_starting()

    def set_ready(self):
        plugins.on('ready', self)

    def _has_support_network_for(self, factor):
        bond_factor = self._config['personality']['bond_encounters_factor']
        total_encounters = sum(peer.encounters for _, peer in self._peers.items())
        support_factor = total_encounters / bond_factor
        return support_factor >= factor

    # triggered when it's a sad/bad day but you have good friends around ^_^
    def set_grateful(self):
        self._view.on_grateful()
        plugins.on('grateful', self)

    def set_lonely(self):
        if not self._has_support_network_for(1.0):
            self._view.on_lonely()
            plugins.on('lonely', self)
        else:
            self.set_grateful()

    def set_bored(self):
        factor = self._epoch.inactive_for / self._config['personality']['bored_num_epochs']
        if not self._has_support_network_for(factor):
            logging.warning("%d epochs with no activity -> bored" % self._epoch.inactive_for)
            self._view.on_bored()
            plugins.on('bored', self)
        else:
            self.set_grateful()

    def set_sad(self):
        factor = self._epoch.inactive_for / self._config['personality']['sad_num_epochs']
        if not self._has_support_network_for(factor):
            logging.warning("%d epochs with no activity -> sad" % self._epoch.inactive_for)
            self._view.on_sad()
            plugins.on('sad', self)
        else:
            self.set_grateful()

    def set_excited(self):
        logging.warning("%d epochs with activity -> excited" % self._epoch.active_for)
        self._view.on_excited()
        plugins.on('excited', self)

    def set_rebooting(self):
        self._view.on_rebooting()
        plugins.on('rebooting', self)

    def wait_for(self, t, sleeping=True):
        plugins.on('sleep' if sleeping else 'wait', self, t)
        self._view.wait(t, sleeping)
        self._epoch.track(sleep=True, inc=t)

    def is_stale(self):
        return self._epoch.num_missed > self._config['personality']['max_misses_for_recon']

    def any_activity(self):
        return self._epoch.any_activity

    def next_epoch(self):
        was_stale = self.is_stale()
        did_miss = self._epoch.num_missed

        self._epoch.next()

        # after X misses during an epoch, set the status to lonely
        if was_stale:
            logging.warning("agent missed %d interactions -> lonely" % did_miss)
            self.set_lonely()
        # after X times being bored, the status is set to sad
        elif self._epoch.inactive_for >= self._config['personality']['sad_num_epochs']:
            self.set_sad()
        # after X times being inactive, the status is set to bored
        elif self._epoch.inactive_for >= self._config['personality']['bored_num_epochs']:
            self.set_bored()
        # after X times being active, the status is set to happy / excited
        elif self._epoch.active_for >= self._config['personality']['excited_num_epochs']:
            self.set_excited()
        elif self._has_support_network_for(1.0):
            self.set_grateful()

        plugins.on('epoch', self, self._epoch.epoch - 1, self._epoch.data())

        if self._epoch.blind_for >= self._config['main']['mon_max_blind_epochs']:
            logging.critical("%d epochs without visible access points -> rebooting ..." % self._epoch.blind_for)
            self._reboot()
            self._epoch.blind_for = 0
