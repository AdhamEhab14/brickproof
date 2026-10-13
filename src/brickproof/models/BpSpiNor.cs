// An SPI NOR flash chip for the emulator (the 25-series command set: Winbond W25Q,
// Macronix MX25, GigaDevice GD25 and their like), built for BrickProof.
//
// Renode has SPI flash models of its own. They store what they are told and that is all.
// This one does for an external flash chip what the STM32 flash models next to it do for
// the internal flash:
//
//   every page program and every erase is an operation: counted, traced, and the place
//     where a power cut can fall. The count, the cut point and the trace switch are the
//     same ones the internal flash model uses (they live in the bpState memory), so the
//     operations of both memories are numbered in the order they really happened;
//   a program can only clear bits, and wraps inside its 256-byte page, as on the chip;
//   nothing is written or erased without a write enable before it;
//   the status register's block protection (BP0-2, TB, SEC, and CMP in status register 2)
//     refuses an erase or a program that touches a protected part, as the chip does. The
//     refusal is counted and traced like the internal flash's write protection, and fails
//     the run. The status registers are non-volatile: they survive a power cut, and the
//     engine saves and restores them with the chip's contents;
//   operations take the time the datasheet gives them. The CPU is not stalled by an
//     external chip, but firmware waits for the busy bit, so the time is skipped the
//     same way and the busy bit never reads as set.
//
// The chip's contents are kept in here, not on the system bus. The engine loads, saves
// and compares them through the methods at the end, with files.
//
// Chip select comes in as GPIO 0, active low: the command runs when it goes high.
using System;
using System.Collections.Generic;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.SPI
{
    public class BpSpiNor : ISPIPeripheral, IGPIOReceiver
    {
        public BpSpiNor(IMachine machine, int size, ulong address, ulong state, string traceFile,
            int timing = 1, uint jedecId = 0xEF4015, int status1 = 0, int status2 = 0,
            int protectUnit = 0x10000)
        {
            this.machine = machine;
            this.address = address;
            this.state = state;
            this.traceFile = traceFile;
            this.timing = timing;
            this.jedecId = jedecId;
            this.protectUnit = protectUnit;
            SetStatus(status1 | (status2 << 8));
            memory = new byte[size];
            for(var i = 0; i < size; i++)
            {
                memory[i] = 0xFF;
            }
            selected = false;
        }

        public void Reset()
        {
            // a reset of the machine is not a power cycle of this chip's contents
            writeEnabled = false;
            selected = false;
            bytes.Clear();
        }

        public void OnGPIO(int number, bool value)
        {
            if(number != 0)
            {
                return;
            }
            if(!value)
            {
                selected = true;
                bytes.Clear();
            }
            else if(selected)
            {
                selected = false;
                Execute();
                bytes.Clear();
            }
        }

        public void FinishTransmission()
        {
            // the controller does not know about chip select; the GPIO does
        }

        public byte Transmit(byte data)
        {
            if(!selected)
            {
                return 0xFF;
            }
            bytes.Add(data);
            var n = bytes.Count;
            switch(bytes[0])
            {
                case ReadStatus:
                    return (byte)((sr1 & 0xFC) | (writeEnabled ? 0x02 : 0x00));  // never busy, see the top
                case ReadStatus2:
                    return sr2;
                case ReadJedecId:
                    return n >= 2 && n <= 4 ? (byte)(jedecId >> (8 * (4 - n))) : (byte)0;
                case Read:
                    return n > 4 ? At(Address() + (uint)(n - 5)) : (byte)0;
                case FastRead:
                    return n > 5 ? At(Address() + (uint)(n - 6)) : (byte)0;
                default:
                    return 0;
            }
        }

        // ---- commands that change something run when chip select is released --------

        private void Execute()
        {
            if(bytes.Count == 0)
            {
                return;
            }
            switch(bytes[0])
            {
                case WriteEnable:
                    writeEnabled = true;
                    break;
                case WriteDisable:
                    writeEnabled = false;
                    break;
                case WriteStatus:
                    // one byte writes status register 1, a second byte status register 2
                    if(writeEnabled && bytes.Count >= 2)
                    {
                        sr1 = (byte)(bytes[1] & 0xFC);
                        if(bytes.Count >= 3)
                        {
                            WriteStatus2Byte(bytes[2]);
                        }
                    }
                    writeEnabled = false;
                    break;
                case WriteStatus2:
                    if(writeEnabled && bytes.Count >= 2)
                    {
                        WriteStatus2Byte(bytes[1]);
                    }
                    writeEnabled = false;
                    break;
                case PageProgram:
                    if(writeEnabled && bytes.Count > 4)
                    {
                        Program(Address(), bytes.GetRange(4, bytes.Count - 4));
                    }
                    writeEnabled = false;
                    break;
                case SectorErase:
                    Erase(4 * 1024, sectorEraseUs);
                    break;
                case BlockErase32:
                    Erase(32 * 1024, block32EraseUs);
                    break;
                case BlockErase64:
                    Erase(64 * 1024, block64EraseUs);
                    break;
                case ChipErase:
                case ChipEraseAlt:
                    if(writeEnabled && Begin(true, address))
                    {
                        if(Protects(0, (uint)memory.Length))
                        {
                            Refuse(address);    // the chip erases nothing if any part is protected
                        }
                        else
                        {
                            Fill(0, memory.Length);
                            Log(String.Format("E 0x{0:X8} #0x{1:X} @{2}", address, memory.Length,
                                Spend(chipEraseUs[timing] * (memory.Length / (1024 * 1024) + 1))));
                        }
                    }
                    writeEnabled = false;
                    break;
            }
        }

        private void Erase(int length, int[] us)
        {
            if(writeEnabled && bytes.Count >= 4)
            {
                var start = Address() / (uint)length * (uint)length;
                if(start < memory.Length && Begin(true, address + start))
                {
                    if(Protects(start, (uint)length))
                    {
                        Refuse(address + start);
                        writeEnabled = false;
                        return;
                    }
                    Fill((int)start, length);
                    Log(String.Format("E 0x{0:X8} #0x{1:X} @{2}", address + start, length, Spend(us[timing])));
                }
            }
            writeEnabled = false;
        }

        private void Program(uint at, List<byte> data)
        {
            if(at >= memory.Length || !Begin(false, 0))
            {
                return;
            }
            // more than a page of data: the chip keeps the last 256 bytes. And the
            // address wraps inside the page it started in.
            if(data.Count > PageSize)
            {
                data = data.GetRange(data.Count - PageSize, PageSize);
            }
            var page = at / PageSize * PageSize;
            if(Protects(page, PageSize))
            {
                Refuse(address + at);
                return;
            }
            var stored = new byte[data.Count];
            var contiguous = (at % PageSize) + data.Count <= PageSize;
            for(var i = 0; i < data.Count; i++)
            {
                var where = page + (uint)((at % PageSize + i) % PageSize);
                memory[where] &= data[i];       // a program clears bits, it cannot set them
                stored[i] = memory[where];
            }
            if(contiguous)
            {
                Log(String.Format("P 0x{0:X8} 0x{1} @{2}", address + at, LittleEndianHex(stored), Spend(programUs[timing])));
            }
            else
            {
                // a wrapped program is traced as the page it ended up as
                var whole = new byte[PageSize];
                Array.Copy(memory, page, whole, 0, PageSize);
                Log(String.Format("P 0x{0:X8} 0x{1} @{2}", address + page, LittleEndianHex(whole), Spend(programUs[timing])));
            }
        }

        // ---- write protection -------------------------------------------------------

        private bool Protects(uint start, uint length)
        {
            // Does the status register protect any byte of [start, start + length)?
            // The W25Q16JV table (WPS = 0): BP = 0 protects nothing, BP = 11x everything.
            // With SEC = 0, BP = 001 protects protectUnit (64 KB on a W25Q16JV) at the top,
            // or with TB at the bottom, and each step up doubles it. With SEC = 1 the steps
            // are 4, 8, 16 and 32 KB. CMP protects the complement instead.
            var size = (uint)memory.Length;
            var bp = (sr1 >> 2) & 7;
            var top = ((sr1 >> 5) & 1) == 0;
            uint lo = 0, hi = 0;
            if(bp >= 6)
            {
                hi = size;
            }
            else if(bp != 0)
            {
                var span = ((sr1 >> 6) & 1) == 1
                    ? (uint)(0x1000 << Math.Min(bp - 1, 3))
                    : (uint)Math.Min((long)protectUnit << (bp - 1), size);
                lo = top ? size - span : 0;
                hi = top ? size : span;
            }
            var end = start + length;
            if(((sr2 >> 6) & 1) == 1)
            {
                return start < lo || end > hi;      // everything outside [lo, hi) is protected
            }
            return start < hi && end > lo;
        }

        private void Refuse(ulong where)
        {
            // counted where the internal flash model counts its write-protection refusals
            if(State(Protected) == 0)
            {
                SetState(ProtectedAt, (uint)where);
            }
            SetState(Protected, State(Protected) + 1);
            Log(String.Format("W 0x{0:X8}", where));
        }

        private void WriteStatus2Byte(byte value)
        {
            // QE and CMP are written; SRL and the security register locks are one-time
            // programmable (they only go from 0 to 1); SUS is read-only
            sr2 = (byte)((sr2 & 0x39) | (value & 0x42) | (value & 0x39));
        }

        // ---- the operation count and the cut, shared with the internal flash model ---

        private bool Begin(bool erasing, ulong where)
        {
            // One operation is about to start. False if this is where the power goes:
            // the CPU is stopped and the operation must not happen.
            if(State(CutHit) != 0)
            {
                return false;
            }
            var count = State(OpCount);
            if(count == State(CutPoint) || (erasing && where == State(CutPage)))
            {
                SetState(CutHit, 1);
                SetState(CutKind, erasing ? 1u : 2u);
                SetState(CutAddr, erasing ? (uint)where : 0);
                foreach(var cpu in machine.SystemBus.GetCPUs())
                {
                    cpu.IsHalted = true;
                }
                return false;
            }
            SetState(OpCount, count + 1);
            return true;
        }

        private int Spend(int us)
        {
            if(us > 0)
            {
                foreach(var cpu in machine.SystemBus.GetCPUs())
                {
                    var skip = cpu.GetType().GetMethod("SkipTime");
                    if(skip != null)
                    {
                        skip.Invoke(cpu, new object[] { TimeInterval.FromMicroseconds((ulong)us) });
                    }
                }
            }
            return us;
        }

        private void Log(string line)
        {
            if(State(Trace) == 1)
            {
                File.AppendAllText(traceFile, line + "\n");
            }
        }

        private uint State(int index)
        {
            return machine.SystemBus.ReadDoubleWord(state + 4 * (ulong)index);
        }

        private void SetState(int index, uint value)
        {
            machine.SystemBus.WriteDoubleWord(state + 4 * (ulong)index, value);
        }

        // ---- small things ------------------------------------------------------------

        private uint Address()
        {
            return bytes.Count >= 4 ? (uint)((bytes[1] << 16) | (bytes[2] << 8) | bytes[3]) : 0;
        }

        private byte At(uint where)
        {
            return memory[where % (uint)memory.Length];
        }

        private void Fill(int start, int length)
        {
            for(var i = start; i < start + length && i < memory.Length; i++)
            {
                memory[i] = 0xFF;
            }
        }

        private static string LittleEndianHex(byte[] data)
        {
            // as one number whose least significant byte is the first byte stored
            var chars = new char[2 * data.Length];
            for(var i = 0; i < data.Length; i++)
            {
                var text = data[data.Length - 1 - i].ToString("X2");
                chars[2 * i] = text[0];
                chars[2 * i + 1] = text[1];
            }
            return new string(chars);
        }

        // ---- for the engine, through the monitor ---------------------------------------

        public void LoadAt(string path, uint offset)
        {
            var data = File.ReadAllBytes(path);
            Array.Copy(data, 0, memory, offset, Math.Min(data.Length, memory.Length - (int)offset));
        }

        public int GetStatus()
        {
            // both status registers, for the engine's flash image: register 1 in the low byte
            return (sr1 & 0xFC) | (sr2 << 8);
        }

        public void SetStatus(int value)
        {
            sr1 = (byte)(value & 0xFC);
            sr2 = (byte)((value >> 8) & 0x7F);
        }

        public void SaveTo(string path)
        {
            File.WriteAllBytes(path, memory);
        }

        public long Mismatch(string path, uint offset)
        {
            // first offset where the chip differs from the file laid at `offset`, or -1
            var data = File.ReadAllBytes(path);
            for(var i = 0; i < data.Length && offset + i < memory.Length; i++)
            {
                if(memory[offset + i] != data[i])
                {
                    return offset + i;
                }
            }
            return -1;
        }

        private bool selected;
        private bool writeEnabled;
        private byte sr1, sr2;                  // non-volatile: a reset does not touch them
        private readonly int protectUnit;
        private readonly List<byte> bytes = new List<byte>();
        private readonly byte[] memory;
        private readonly IMachine machine;
        private readonly ulong address;
        private readonly ulong state;
        private readonly string traceFile;
        private readonly int timing;
        private readonly uint jedecId;

        private const int PageSize = 256;
        private const byte WriteEnable = 0x06, WriteDisable = 0x04, ReadStatus = 0x05, ReadJedecId = 0x9F;
        private const byte ReadStatus2 = 0x35, WriteStatus = 0x01, WriteStatus2 = 0x31;
        private const byte Read = 0x03, FastRead = 0x0B, PageProgram = 0x02;
        private const byte SectorErase = 0x20, BlockErase32 = 0x52, BlockErase64 = 0xD8;
        private const byte ChipErase = 0xC7, ChipEraseAlt = 0x60;
        // the indices of the shared state words, as in the STM32 flash models
        private const int OpCount = 1, CutPoint = 2, CutHit = 3, CutKind = 4, CutAddr = 5, CutPage = 6, Trace = 9;
        private const int Protected = 19, ProtectedAt = 20;

        // How long operations take, in microseconds: none, typical, the slowest allowed.
        // From the Winbond W25Q16JV datasheet (AC characteristics): page program 0.4 / 3 ms,
        // 4 KB sector erase 45 / 400 ms, 32 KB block 120 / 1600 ms, 64 KB block 150 / 2000 ms,
        // chip erase 5 / 25 s for 2 MB (scaled here per megabyte).
        private static readonly int[] programUs = { 0, 400, 3000 };
        private static readonly int[] sectorEraseUs = { 0, 45000, 400000 };
        private static readonly int[] block32EraseUs = { 0, 120000, 1600000 };
        private static readonly int[] block64EraseUs = { 0, 150000, 2000000 };
        private static readonly int[] chipEraseUs = { 0, 2500000, 12500000 };
    }
}
