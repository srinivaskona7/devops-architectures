---
title: Boot process, GRUB and recovery
minutes: 45
objectives:
  - Describe each stage from firmware to login
  - Edit kernel parameters at the GRUB menu and boot into rescue modes
  - Rebuild an initramfs and reinstall the boot loader
  - Recover a cloud instance that will not boot
---
A server that does not boot is a rare but high-stress event. Knowing the stages tells you where to look. Commands for GRUB differ between Debian-family (`update-grub`) and Red Hat-family (`grub2-mkconfig`) systems.

@concept The boot sequence
@plain
Booting is a relay: firmware starts a boot loader, which loads the kernel and an initial RAM disk, which mounts the real root filesystem, which starts systemd.
@problem
"It will not boot" could mean five different things. Each stage prints different messages, and the fix differs.
@does
- **Firmware** (UEFI, or BIOS on old systems) initialises hardware and finds the boot loader.
- **Boot loader** (GRUB) shows a menu and loads the kernel and initramfs into memory.
- **Kernel** starts, finds the initramfs and runs its `/init`.
- **initramfs** loads drivers needed to see the root disk, then mounts the root and switches to it.
- **systemd** (PID 1) starts services up to the default target.
@diagram flow
caption: Stages of boot and typical failures
numbered: true
nodes:
  - "UEFI|no boot device found|info"
  - "GRUB|grub rescue prompt|app"
  - "Kernel|panic, cannot mount root|warn"
  - "initramfs|dropped to emergency shell|env"
  - "systemd|emergency or degraded target|ok"
@h See your own boot
```bash title="Boot facts" lab
[ -d /sys/firmware/efi ] && echo "UEFI boot" || echo "legacy BIOS boot"
cat /proc/cmdline                         # kernel parameters used this boot
systemd-analyze blame --no-pager | head -8
ls /boot | head -12
```
@check
Which stage loads the drivers needed to mount root? || The initramfs.
@end

@concept UEFI, the ESP and partitions
@plain
UEFI systems keep boot loaders on a small FAT-formatted **EFI System Partition** (ESP), usually mounted at `/boot/efi`. Legacy BIOS systems use the first sector of the disk.
@problem
Overwriting or unmounting the ESP, or mixing up boot modes, is a common reason a reinstalled loader does nothing.
@does
- `efibootmgr -v` lists firmware boot entries and their order.
- The partition table is GPT for UEFI (MBR for BIOS). `lsblk -f` and `blkid` show filesystems and UUIDs.
- Secure Boot only runs signed loaders; distribution packages ship a signed shim.
- Cloud images often hide this; the provider console or serial console is your screen.
@diagram layers
caption: A typical UEFI disk
layers:
  - {label: "GPT", nodes: ["Partition table|primary and backup copy|plain"]}
  - {label: "Partitions", nodes: ["ESP, FAT32|about 512 MiB, boot loaders|cp", "/boot|kernels and initramfs|env", "Root|ext4 or xfs, LVM optional|app"]}
@h Inspect
```bash title="Disk and firmware entries" lab
lsblk -f
findmnt /boot/efi 2>/dev/null
sudo efibootmgr -v 2>/dev/null | head -6
sudo blkid | head -5
```
@end

@concept GRUB configuration and kernel parameters
@plain
GRUB reads `/boot/grub/grub.cfg`, which is generated. You edit `/etc/default/grub` and regenerate; you do not edit grub.cfg by hand.
@problem
Direct edits to the generated file are overwritten on the next kernel update, and mistakes there leave the system unbootable.
@does
- `GRUB_CMDLINE_LINUX` adds permanent parameters (for example `console=ttyS0` for cloud serial console, or `quiet`).
- Regenerate with `update-grub` (Debian family) or `grub2-mkconfig -o /boot/grub2/grub.cfg` (Red Hat family; UEFI path differs on older releases, check your docs).
- At the menu press `e` to edit the entry for one boot only. Useful temporary parameters: `systemd.unit=rescue.target`, `init=/bin/bash`, `nomodeset`, `single`.
@diagram seq
caption: One-time kernel parameter edit
actors: ["Admin|serial or VM console|app", "GRUB|boot menu|cp"]
steps:
  - "0>1: press e on the entry | req"
  - "0>1: append systemd.unit=rescue.target | req"
  - "0>1: Ctrl-X to boot | req"
  - "1>0: boots to rescue shell | resp"
@h Make a persistent change
```bash title="Safe GRUB edit" nocheck
sudo cp /etc/default/grub /etc/default/grub.bak
sudo sed -i 's/^GRUB_CMDLINE_LINUX=.*/GRUB_CMDLINE_LINUX="console=tty0 console=ttyS0,115200n8"/' /etc/default/grub
grep ^GRUB_CMDLINE /etc/default/grub
sudo update-grub                              # Debian family
# sudo grub2-mkconfig -o /boot/grub2/grub.cfg    # Red Hat family
sudo reboot
```
:::warn
Test changes to boot parameters with a one-time edit at the menu first, and keep console access (cloud serial console) available before you reboot a remote machine.
:::
@check
Why not edit grub.cfg directly? || It is generated and will be overwritten; edit /etc/default/grub and regenerate.
@end

@concept Rescue and emergency modes
@plain
systemd has two repair targets. **rescue.target** mounts local filesystems and starts basic services with a root shell. **emergency.target** mounts only the root filesystem read-only and starts almost nothing.
@problem
A bad line in `/etc/fstab`, a failed filesystem check or a broken unit can drop a server into a minimal shell that confuses people.
@does
- Emergency shell asks for the root password (not available if root is locked; cloud images need a rescue instance instead).
- Remount root read-write: `mount -o remount,rw /`.
- Check `journalctl -xb` for the failing mount or unit; fix `/etc/fstab`; test with `mount -a` before rebooting.
- Use `nofail` and `x-systemd.device-timeout=` on non-essential mounts so a missing volume does not block boot.
@diagram flow
caption: Typical recovery path after a bad fstab
numbered: true
nodes:
  - "Emergency shell|boot stopped|bad"
  - "Remount rw|mount -o remount,rw /|info"
  - "Fix fstab|comment the bad line|app"
  - "mount -a|prove it works|warn"
  - "Reboot|normal boot|ok"
@h In the shell
```bash title="Repair fstab" nocheck
journalctl -xb | grep -iE 'failed|dependency' | head
mount -o remount,rw /
vi /etc/fstab                       # add nofail or fix the UUID, find UUIDs with blkid
mount -a && echo "fstab OK"
systemctl daemon-reload && reboot
```
@check
How do you verify fstab changes without rebooting? || Run `mount -a`, which tries every entry.
@end

@concept initramfs
@plain
The **initramfs** is a small compressed filesystem loaded with the kernel. It contains just enough modules and scripts to find and unlock the root device.
@problem
If the root disk needs a driver (NVMe, LVM, RAID, encrypted volume) and the initramfs lacks it, the kernel panics with "unable to mount root fs".
@does
- Regenerate with `update-initramfs -u -k all` (Debian family) or `dracut -f` (Red Hat family).
- Inspect contents with `lsinitramfs` (Debian) or `lsinitrd` (dracut).
- After changing storage (adding LVM, moving to NVMe) or driver options, rebuild.
- Cloud kernels ship their own; regenerate after kernel or module changes.
@diagram flow
caption: What the initramfs does
nodes:
  - "Kernel starts|unpacks initramfs|cp"
  - "Load drivers|nvme, lvm, crypt|app"
  - "Find root|UUID from cmdline|info"
  - "switch_root|hand over to real root|ok"
@h Inspect and rebuild
```bash title="Look inside and regenerate" nocheck
ls -lh /boot/initrd.img-* /boot/initramfs-* 2>/dev/null | head
lsinitramfs /boot/initrd.img-$(uname -r) 2>/dev/null | grep -E 'nvme|lvm|ext4' | head
sudo update-initramfs -u -k "$(uname -r)"        # Debian family
# sudo dracut -f --kver "$(uname -r)"             # Red Hat family
```
@check
What error suggests a missing driver in initramfs? || Kernel panic, unable to mount root fs, or a drop to the initramfs shell.
@end

@concept Repairing GRUB from a live system or chroot
@plain
If the boot loader is damaged, boot another system, mount the broken one, `chroot` into it and reinstall GRUB.
@problem
After disk cloning, a partition change or an OS dual boot, the boot entry can disappear and the machine shows "no bootable device" or a `grub>` prompt.
@does
- Boot a live ISO or a rescue instance (in the cloud: attach the volume to a second instance).
- Mount root, then bind `/dev`, `/proc`, `/sys`, and the ESP; `chroot` in; run `grub-install` and `update-grub`.
- At the `grub rescue>` prompt you can set `root` and `prefix`, then `insmod normal` and `normal`, to boot once and repair from inside.
@diagram flow
caption: Reinstalling the loader
numbered: true
nodes:
  - "Boot live system|ISO or rescue instance|info"
  - "Mount and bind|root, ESP, dev, proc, sys|app"
  - "chroot|work inside the broken OS|cp"
  - "grub-install, update-grub|rewrite loader and config|warn"
  - "Reboot|from the disk|ok"
@h Procedure
```bash title="chroot repair on UEFI" nocheck
sudo mount /dev/nvme0n1p2 /mnt                       # root, adjust device names with lsblk
sudo mount /dev/nvme0n1p1 /mnt/boot/efi              # ESP
for d in dev proc sys; do sudo mount --rbind /$d /mnt/$d; done
sudo chroot /mnt /bin/bash
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu
update-grub && exit
sudo umount -R /mnt && sudo reboot
```
:::danger
Confirm device names with `lsblk -f` before every mount or install. Writing a loader to the wrong disk can make a healthy system unbootable.
:::
@end

@concept Cloud instances that will not boot
@plain
In the cloud you have no physical console but you do have the **serial console** and the ability to move a disk to another instance.
@problem
A bad fstab, a broken sshd config or a full root disk leaves the instance running but unreachable, so you cannot log in to fix it.
@does
- Use the provider's serial console (EC2 Serial Console, check current docs) or system log screenshot to see boot messages.
- Rescue procedure: stop the instance, detach its root volume, attach it to a helper instance in the same zone as a secondary disk, mount it, fix the file, unmount, reattach as the original device name and start.
- Snapshot the volume first. Prevent recurrence with `nofail` mounts, `sshd -t` before reload, and monitoring of disk usage.
- Immutable infrastructure avoids many repairs: replace the instance from a known good image instead.
@diagram flow
caption: EBS volume rescue
numbered: true
nodes:
  - "Snapshot|safety copy|ok"
  - "Stop and detach|root volume|warn"
  - "Attach to helper|as /dev/sdf|info"
  - "Mount and fix|fstab or sshd_config|app"
  - "Reattach and start|original device name|ok"
@h Commands
```bash title="Rescue with the AWS CLI" nocheck
aws ec2 create-snapshot --volume-id vol-0123456789abcdef0 --description "pre-rescue"
aws ec2 stop-instances --instance-ids i-0aaaabbbbccccdddd
aws ec2 detach-volume --volume-id vol-0123456789abcdef0
aws ec2 attach-volume --volume-id vol-0123456789abcdef0 --instance-id i-0helper0000000000 --device /dev/sdf
# on the helper: lsblk; sudo mount /dev/nvme1n1p1 /mnt; fix files; sudo umount /mnt
```
@check
Why snapshot the volume before rescuing? || So a mistake during the repair can be undone.
@end
