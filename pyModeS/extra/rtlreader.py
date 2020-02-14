import numpy as np
import pyModeS as pms
from rtlsdr import RtlSdr
import time

sampling_rate = 2e6
smaples_per_microsec = 2

modes_frequency = 1090e6
buffer_size = 1024 * 100
read_size = 1024 * 10

pbits = 8
fbits = 112
preamble = [1, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0]
# th_amp = 0.2  # signal amplitude threshold for 0 and 1 bit
th_amp_diff = 0.8  # signal amplitude threshold difference between 0 and 1 bit


class RtlReader(object):
    def __init__(self, **kwargs):
        super(RtlReader, self).__init__()
        self.signal_buffer = []  # amplitude of the sample only
        self.sdr = RtlSdr()
        self.sdr.sample_rate = sampling_rate
        self.sdr.center_freq = modes_frequency
        self.sdr.gain = "auto"

        self.debug = kwargs.get("debug", False)
        self.raw_pipe_in = None
        self.stop_flag = False
        self.noise_floor = 1e6

    def _calc_noise(self):
        """Calculate noise floor"""
        window = smaples_per_microsec * 100
        means = np.array(self.signal_buffer).reshape(-1, window).mean(axis=1)
        return min(means)

    def _process_buffer(self):
        """process raw IQ data in the buffer"""

        # update noise floor
        self.noise_floor = min(self._calc_noise(), self.noise_floor)

        # set minimum signal amplitude
        min_sig_amp = 3.162 * self.noise_floor  # 10 dB SNR

        # Mode S messages
        messages = []

        buffer_length = len(self.signal_buffer)

        i = 0
        while i < buffer_length:
            if self.signal_buffer[i] < min_sig_amp:
                i += 1
                continue

            if self._check_preamble(self.signal_buffer[i : i + pbits * 2]):
                frame_start = i + pbits * 2
                frame_end = i + pbits * 2 + (fbits + 1) * 2
                frame_length = (fbits + 1) * 2
                frame_pulses = self.signal_buffer[frame_start:frame_end]

                threshold = max(frame_pulses) * 0.2

                msgbin = []
                for j in range(0, frame_length, 2):
                    p2 = frame_pulses[j : j + 2]
                    if len(p2) < 2:
                        break

                    if p2[0] < threshold and p2[1] < threshold:
                        break
                    elif p2[0] >= p2[1]:
                        c = 1
                    elif p2[0] < p2[1]:
                        c = 0
                    else:
                        msgbin = []
                        break

                    msgbin.append(c)

                # advance i with a jump
                i = frame_start + j

                if len(msgbin) > 0:
                    msghex = pms.bin2hex("".join([str(i) for i in msgbin]))
                    if self._check_msg(msghex):
                        messages.append([msghex, time.time()])
                    if self.debug:
                        self._debug_msg(msghex)

            # elif i > buffer_length - 500:
            #     # save some for next process
            #     break
            else:
                i += 1

        # reset the buffer
        self.signal_buffer = self.signal_buffer[i:]

        return messages

    def _check_preamble(self, pulses):
        if len(pulses) != 16:
            return False

        for i in range(16):
            if abs(pulses[i] - preamble[i]) > th_amp_diff:
                return False

        return True

    def _check_msg(self, msg):
        df = pms.df(msg)
        msglen = len(msg)
        if df == 17 and msglen == 28:
            if pms.crc(msg) == 0:
                return True
        elif df in [20, 21] and msglen == 28:
            return True
        elif df in [4, 5, 11] and msglen == 14:
            return True

    def _debug_msg(self, msg):
        df = pms.df(msg)
        msglen = len(msg)
        if df == 17 and msglen == 28:
            print(msg, pms.icao(msg), pms.crc(msg))
        elif df in [20, 21] and msglen == 28:
            print(msg, pms.icao(msg))
        elif df in [4, 5, 11] and msglen == 14:
            print(msg, pms.icao(msg))
        else:
            # print("[*]", msg)
            pass

    def _read_callback(self, data, rtlsdr_obj):
        amp = np.absolute(data)
        self.signal_buffer.extend(amp.tolist())

        if len(self.signal_buffer) >= buffer_size:
            messages = self._process_buffer()
            self.handle_messages(messages)

    def handle_messages(self, messages):
        """re-implement this method to handle the messages"""
        for msg, t in messages:
            # print("%15.9f %s" % (t, msg))
            pass

    def stop(self, *args, **kwargs):
        self.sdr.cancel_read_async()

    def run(self, raw_pipe_in=None, stop_flag=None):
        self.raw_pipe_in = raw_pipe_in
        self.stop_flag = stop_flag
        self.sdr.read_samples_async(self._read_callback, read_size)

        # count = 1
        # while count < 1000:
        #     count += 1
        #     data = self.sdr.read_samples(read_size)
        #     self._read_callback(data, None)


if __name__ == "__main__":
    import signal

    rtl = RtlReader()
    signal.signal(signal.SIGINT, rtl.stop)

    rtl.debug = True
    rtl.run()
