"""Bad update content: the update is not cut, the image itself is wrong.

A bootloader has to refuse an image that is truncated, has a bit flipped in its header,
its body or its signature area, or was signed with another key, is older than the
running one, is meant for another slot. Each content fault replaces the staged image
with a damaged one, lets the update run to the end, and judges the device from outside:
the image named by `keep` (the one running before) must still be installed and running,
not in a fault handler. The firmware's own word is not needed, so these tests use the
oracle and the driver's `alive()` only.

scenario.content_faults:
  keep          the oracle image that must still be installed and running (required)
  image_size    bytes of the staged file that are the image; the rest (a padded slot's
                trailer, for example) is left as it is. Default: read from the image when
                it is an MCUboot image, else the whole file
  mutations     which built-in ones to run (default all): truncate, flip, erased
  regions       {name: [start, end]} offsets in the staged image to flip one bit in, each
                at its middle. Default: an MCUboot image's header, body and TLV area
                (hash and signature), read from it; else one region, the whole image
  images        {name: file}: bad images made outside BrickProof (another key, an older
                version, built for another slot), staged as they are
"""
from brickproof import images

MUTATIONS = ("truncate", "flip", "erased")
KEYS = {"keep", "image_size", "mutations", "regions", "images"}


def layout(staged, cfg):
    """(image size, regions) for the damaged-image tests: what the adapter gives, else what
    an MCUboot image's header says, else the whole file as one region. Read from the image,
    a rebuild that changes its size cannot leave a stale number behind."""
    found = images.mcuboot_layout(staged)
    size = cfg.get("image_size") or (found.size if found else len(staged))
    regions = cfg.get("regions")
    if not regions:
        regions = ({"header": found.header, "body": found.body, "tlv": found.tlv}
                   if found and not cfg.get("image_size") else {"image": (0, size)})
    return size, regions


def mutations(staged, cfg, files=None):
    """[(name, bytes)]: every damaged version of the staged file to try. `files` gives the
    bytes of each adapter-supplied image by name."""
    size, regions = layout(staged, cfg)
    head, tail = staged[:size], staged[size:]
    out = []

    def staged_with(image):
        # a damaged image in the image's place, the rest of the staged file (a trailer
        # that asks for the update) as it was
        image = bytes(image[:size]) + b"\xFF" * max(0, size - len(image))
        return image + tail

    wanted = cfg.get("mutations") or MUTATIONS
    if "truncate" in wanted:
        for n in sorted({size // 4, size // 2, 3 * size // 4, size - 4}):
            if 0 < n < size:
                out.append(("truncate-%d" % n, staged_with(head[:n])))
    if "flip" in wanted:
        for name, (start, end) in sorted(regions.items()):
            at = (start + end) // 2
            damaged = bytearray(head)
            damaged[at] ^= 0x01
            out.append(("flip-%s@0x%X" % (name, at), staged_with(damaged)))
    if "erased" in wanted:
        out.append(("erased", staged_with(b"")))
    for name, data in sorted((files or {}).items()):
        if len(data) > len(staged):
            # bigger than what was staged: stage it whole, it is the point of the test
            out.append((name, bytes(data)))
        else:
            out.append((name, bytes(data) + staged[len(data):] if len(data) >= size
                        else staged_with(data)))
    return out
