// An I2C EEPROM for the emulator (the 24-series: 24C32 to 24C512 and their like), built for
// BrickProof. It does for an EEPROM what the flash models do for flash:
//
//   every write is an operation: counted, traced, and the place where a power cut can fall.
//     The count, the cut point and the trace switch are the internal flash model's (in the
//     bpState memory), so the operations of every memory are numbered in the order they
//     really happened;
//   a write covers one page at most: bytes past the end of the page wrap to its start, as
//     on the chip. Unlike flash there is no erase: a write sets each byte to its new value;
//   a write takes the write cycle time the datasheet gives (5 ms). The chip does not answer
//     during it and firmware polls for the acknowledge; here the time is skipped and the
//     chip is never busy, as the SPI flash model does.
//
// The contents are kept in here, not on the system bus. The engine loads, saves and
// compares them through the methods at the end, with files.
using System;
using System.Collections.Generic;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.I2C
{
    public class BpI2cEeprom : II2CPeripheral
    {
        public BpI2cEeprom(IMachine machine, int size, ulong address, ulong state, string traceFile,
            int pageSize = 32, int addressBytes = 2, int timing = 1)
        {
            this.machine = machine;
            this.address = address;
            this.state = state;
            this.traceFile = traceFile;
            this.pageSize = pageSize;
            this.addressBytes = addressBytes;
            this.timing = timing;
            memory = new byte[size];
            for(var i = 0; i < size; i++)
            {
                memory[i] = 0xFF;
            }
        }

        public void Reset()
        {
            // a reset of the machine is not a power cycle of the EEPROM's contents
            incoming.Clear();
        }

        public void Write(byte[] data)
        {
            // one transfer from the controller: the word address first, then the data
            incoming.AddRange(data);
        }

        public byte[] Read(int count = 1)
        {
            // a read goes on from the current address, wrapping at the end of the memory.
            // After a repeated start the word address has come but no stop: take it now.
            if(incoming.Count > 0)
            {
                FinishTransmission();
            }
            var output = new byte[count];
            for(var i = 0; i < count; i++)
            {
                output[i] = memory[current];
                current = (current + 1) % (uint)memory.Length;
            }
            return output;
        }

        public void FinishTransmission()
        {
            // a stop condition: an address alone sets where reads go on from; an address
            // and data is a write
            if(incoming.Count >= addressBytes)
            {
                uint at = 0;
                for(var i = 0; i < addressBytes; i++)
                {
                    at = (at << 8) | incoming[i];
                }
                at %= (uint)memory.Length;
                current = at;
                if(incoming.Count > addressBytes)
                {
                    WritePage(at, incoming.GetRange(addressBytes, incoming.Count - addressBytes));
                }
            }
            incoming.Clear();
        }

        private void WritePage(uint at, List<byte> data)
        {
            if(!Begin())
            {
                return;                         // the power goes before this write
            }
            // more than a page: the chip keeps the last page's worth, wrapped in the page
            if(data.Count > pageSize)
            {
                data = data.GetRange(data.Count - pageSize, pageSize);
            }
            var page = at / (uint)pageSize * (uint)pageSize;
            var contiguous = (at % pageSize) + data.Count <= pageSize;
            for(var i = 0; i < data.Count; i++)
            {
                memory[page + (uint)((at % pageSize + i) % pageSize)] = data[i];
            }
            current = page + (uint)((at % pageSize + data.Count) % pageSize);
            if(contiguous)
            {
                Log(String.Format("P 0x{0:X8} 0x{1} @{2}", address + at,
                    LittleEndianHex(data.ToArray()), Spend(writeUs[timing])));
            }
            else
            {
                // a wrapped write is traced as the page it ended up as
                var whole = new byte[pageSize];
                Array.Copy(memory, page, whole, 0, pageSize);
                Log(String.Format("P 0x{0:X8} 0x{1} @{2}", address + page,
                    LittleEndianHex(whole), Spend(writeUs[timing])));
            }
        }

        // ---- the operation count and the cut, shared with the internal flash model ---

        private bool Begin()
        {
            if(State(CutHit) != 0)
            {
                return false;
            }
            var count = State(OpCount);
            if(count == State(CutPoint))
            {
                SetState(CutHit, 1);
                SetState(CutKind, 2);
                SetState(CutAddr, 0);
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

        public void SaveTo(string path)
        {
            File.WriteAllBytes(path, memory);
        }

        public long Mismatch(string path, uint offset)
        {
            // first offset where the EEPROM differs from the file laid at `offset`, or -1
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

        private uint current;
        private readonly List<byte> incoming = new List<byte>();
        private readonly byte[] memory;
        private readonly IMachine machine;
        private readonly ulong address;
        private readonly ulong state;
        private readonly string traceFile;
        private readonly int pageSize;
        private readonly int addressBytes;
        private readonly int timing;

        // the indices of the shared state words, as in the flash models
        private const int OpCount = 1, CutPoint = 2, CutHit = 3, CutKind = 4, CutAddr = 5, Trace = 9;

        // the write cycle time, in microseconds: none, typical, the slowest allowed (24LC256:
        // 5 ms at most; no typical figure, so taken as the same)
        private static readonly int[] writeUs = { 0, 5000, 5000 };
    }
}
