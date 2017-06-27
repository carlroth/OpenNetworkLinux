#!/bin/sh
#
######################################################################
#
# helper functions for install
#
######################################################################

STAT_F_MPT=

stat_f_capture() {
  local dev dir fsType opts freq passno
  dev=$1; shift
  dir=$1; shift
  fsType=$1; shift
  opts=$1; shift
  freq=$1; shift
  passno=$1; shift

  STAT_F_MPT=$dir

  # readable filesystem type
  STAT_F_T=$fsType

  # hex filesystem type (fake this)
  STAT_F_t=$(echo "$fsType" | md5sum | cut -c 1-4)

  # file name
  STAT_F_n=$rest

  # fundamental block size
  STAT_F_S=$(blockdev --getbsz "$dev" 2>/dev/null || :)
  if test "$STAT_F_S"; then
    :
  else
    STAT_F_S=512
  fi

  # optimal block size
  STAT_F_s=$STAT_F_S
  
  STAT_F_b=
  STAT_F_f=
  STAT_F_a=
  set dummy $(df -P -B $STAT_F_S "$dir" 2>/dev/null | tail -1 || :)
  if test $# -gt 1; then
    # total data blocks
    STAT_F_b=$3

    # free file blocks
    STAT_F_f=$5

    # free blocks for non-superuser (fake this)
    STAT_F_a=$5
  fi

  STAT_F_c=
  STAT_F_d=
  set dummy $(df -P -i "$dir" 2>/dev/null | tail -1 || :)
  if test $# -gt 1; then

    # total inodes
    STAT_F_c=$3

    # free inodes
    STAT_F_d=$5
  fi
}

stat_f_inner() {
  local dev dir fsType opts freq passno rest
  dev=$1; shift
  dir=$1; shift
  fsType=$1; shift
  opts=$1; shift
  freq=$1; shift
  passno=$1; shift
  rest="$@"

  case "$rest" in
    "$dir"|"$dir"/*)
      stat_f_capture "$dev" "$dir" "$fsType" "$opts" "$freq" "$passno"
      return 2
    ;;
  esac

  return 0
}

stat_f_inner_root() {
  local dev dir fsType opts freq passno rest
  dev=$1; shift
  dir=$1; shift
  fsType=$1; shift
  opts=$1; shift
  freq=$1; shift
  passno=$1; shift
  rest="$@"

  if test "$dir" = "/"; then
    :
  else
    return 0
  fi

  stat_f_capture "$dev" "$dir" "$fsType" "$opts" "$freq" "$passno"
  return 2
}

stat_f() {
  local dir opts
  while test $# -gt 1; do
    opts=$opts${opts:+" "}"$1"
    shift
  done
  dir=$1; shift

  STAT_F_MPT=

  visit_proc_mounts stat_f_inner $dir

  # special logic to match top-level mounts
  if test -z "$STAT_F_MPT"; then
    visit_proc_mounts stat_f_inner_root $dir
  fi
  
  if test "$STAT_F_MPT"; then
    echo "stat_f: found mount $STAT_F_MPT for $dir" 1>&2

    opts=$(echo "$opts" | sed -e "s|%t|${STAT_F_t}|")
    opts=$(echo "$opts" | sed -e "s|%T|${STAT_F_T}|")

    opts=$(echo "$opts" | sed -e "s|%n|${STAT_F_n}|")

    opts=$(echo "$opts" | sed -e "s|%s|${STAT_F_s}|")
    opts=$(echo "$opts" | sed -e "s|%S|${STAT_F_S}|")

    opts=$(echo "$opts" | sed -e "s|%b|${STAT_F_b}|")
    opts=$(echo "$opts" | sed -e "s|%f|${STAT_F_f}|")
    opts=$(echo "$opts" | sed -e "s|%a|${STAT_F_a}|")

    opts=$(echo "$opts" | sed -e "s|%c|${STAT_F_c}|")
    opts=$(echo "$opts" | sed -e "s|%d|${STAT_F_d}|")

    stat $opts $STAT_F_MPT
    return 0
  fi

  echo "stat_f: *** cannot find mount point for $dir" 1>&2
  return 1
}

installer_reboot() {
  local dummy sts timeout trapsts
  if test $# -gt 0; then
    timeout=$1; shift
  else
    timeout=3
  fi

  installer_say "Rebooting in ${timeout}s"

  unset dummy trapsts
  # ha ha, 'local' auto-binds the variables

  trap "trapsts=130" 2
  if read -t $timeout -r -p "Hit CR to continue, CTRL-D or CTRL-C to stop... " dummy; then
    sts=0
  else
    sts=$?
  fi
  trap - 2
  test "$trapsts" && sts=$trapsts

  if test ${dummy+set}; then
    if test $sts -eq 0; then
      installer_say "CR, rebooting"
      exit
    else
      installer_say "CTRL-D, stopped"
      exit
    fi
  fi

  # ha ha, busybox does not report SIGALRM
  if test "${trapsts+set}"; then
    :
  else
    installer_say "timeout, rebooting"
    reboot
  fi

  signo=$(( $sts - 128 ))
  if test $signo -eq 14; then
    # SIGALRM, possibly irrelevant for busybox
    installer_say "timeout, rebooting"
    reboot
  fi

  # e.g. SIGQUIT
  installer_say "signal $signo, stopped"
  exit
}

installer_mkchroot() {
  local rootdir
  rootdir=$1

  local hasDevTmpfs
  if grep -q devtmpfs /proc/filesystems; then
    hasDevTmpfs=1
  fi

  # special handling for /dev, which usually already has nested mounts
  installer_say "Setting up /dev"
  rm -fr "${rootdir}/dev"/*
  if test "$hasDevTmpfs"; then
    :
  else
    for dev in /dev/*; do
      if test -d "$dev"; then
        mkdir "${rootdir}${dev}"
      else
        cp -a "$dev" "${rootdir}${dev}"
      fi
    done
    mkdir -p "${rootdir}/dev/pts"
  fi

  installer_say "Setting up /run"
  rm -fr "${rootdir}/run"/*
  mkdir -p "${rootdir}/run"
  d1=$(stat -c "%D" /run)
  for rdir in /run/*; do
    if test -d "$rdir"; then
      mkdir "${rootdir}${rdir}"
      d2=$(stat -c "%D" $rdir)
      t2=$(stat_f -c "%T" $rdir)
      case "$t2" in
        tmpfs|ramfs)
          # skip tmpfs, we'll just inherit the initrd ramfs
        ;;
        *)
          if test "$d1" != "$d2"; then
            mount -o bind $rdir "${rootdir}${rdir}"
          fi
        ;;
      esac
    fi
  done
  
  installer_say "Setting up mounts"
  mount -t proc proc "${rootdir}/proc"
  mount -t sysfs sysfs "${rootdir}/sys"
  if test "$hasDevTmpfs"; then
    mount -t devtmpfs devtmpfs "${rootdir}/dev"
    mkdir -p ${rootdir}/dev/pts
  fi
  mount -t devpts devpts "${rootdir}/dev/pts"

  if test ${TMPDIR+set}; then
    # make the tempdir available to the chroot
    mkdir -p "${rootdir}${TMPDIR}"
  fi

  # export ONIE defines to the installer
  if test -r /etc/machine.conf; then
    cp /etc/machine.conf "${rootdir}/etc/machine.conf"
  fi

  # export ONL defines to the installer
  mkdir -p "${rootdir}/etc/onl"
  if test -d /etc/onl; then
    cp -a /etc/onl/. "${rootdir}/etc/onl/."
  fi

  # export firmware config
  if test -r /etc/fw_env.config; then
    cp /etc/fw_env.config "${rootdir}/etc/fw_env.config"
  fi
}

visit_blkid()
{
  local fn rest
  fn=$1; shift
  rest="$@"

  local ifs
  ifs=$IFS; IFS=$CR
  for line in $(blkid); do
    IFS=$ifs

    local dev
    dev=${line%%:*}
    line=${line#*:}

    local TYPE LABEL PARTLABEL UUID PARTUUID
    while test "$line"; do
      local key
      key=${line%%=*}
      line=${line#*=}
      case "$line" in
        '"'*)
          line=${line#\"}
          val=${line%%\"*}
          line=${line#*\"}
          line=${line## }
        ;;
        *)
          val=${line%% *}
          line=${line#* }
        ;;
      esac
      eval "$key=\"$val\""
    done

    local sts
    if eval $fn \"$dev\" \"$LABEL\" \"$UUID\" \"$PARTLABEL\" \"$PARTUUID\" $rest; then
      sts=0
    else
      sts=$?
    fi
    if test $sts -eq 2; then break; fi
    if test $sts -ne 0; then return $sts; fi

  done
  IFS=$ifs

  return 0
}

# Local variables
# mode: sh
# sh-basic-offset: 2
# End:
