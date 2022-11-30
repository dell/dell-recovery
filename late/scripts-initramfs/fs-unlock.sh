#!/bin/sh
set -x
name=$CRYPTTAB_NAME
tpm_obj=0x81000005

# skip fs-unlock early
[ -e "/dev/disk/by-partlabel/keystore" ] || exit 0

# redicrt console
exec 8<&1
exec 9<&2
logout=/run/initramfs/fs-unlock.out
logerr=/run/initramfs/fs-unlock.out
exec 1>>$logout
exec 2>>$logerr

# funcs
unlock_keystore_by_tpm(){
  local dir4tpm=$(mktemp -d)
  mkdir -p $dir4tpm
  tpm2_startauthsession --policy-session --session $dir4tpm/session.ctx
  tpm2_policypcr --session $dir4tpm/session.ctx --pcr-list sha256:7,8,9 --policy $dir4tpm/unsealing.pcr_sha256_789.policy
  tpm2_unseal -p session:$dir4tpm/session.ctx -c $tpm_obj | cryptsetup open /dev/disk/by-partlabel/keystore keystore --key-slot 2 --priority prefer --key-file=-
  rm -rf $dir4tpm
}

manipulate_keystore_with_hwid(){
  local hwid=$(cat /sys/class/dmi/id/product_serial)
  [ "$hwid" == "" ] && hwid=$(cat /sys/class/dmi/id/product_uuid)
  case "$1" in
    fallback)
      local tmp4hwid=$(mktemp -d)
      mkdir -p $tmp4hwid
      cryptsetup luksKillSlot /dev/disk/by-partlabel/keystore 0 -q
      local new_hwid_key=$tmp4hwid/luks-keystore.keyfile
      printf $hwid | openssl dgst -sha256 -binary -out $new_hwid_key
      plymouth ask-for-password --prompt "Enter PIN to update HWID" --number-of-tries=2 --command="cryptsetup luksAddKey /dev/disk/by-partlabel/keystore $new_hwid_key --key-slot=0 --key-file=-"
      cryptsetup open /dev/disk/by-partlabel/keystore keystore --key-slot 0 --priority prefer --key-file=$new_hwid_key
      return $?
      ;;
    unlock)
      printf $hwid | openssl dgst -sha256 -binary | cryptsetup open /dev/disk/by-partlabel/keystore keystore --key-slot 0 --priority prefer --key-file=-
      return $?
      ;;
    prepare)
      local key_in_use="$2"
      printf $hwid | openssl dgst -sha256 -binary | cryptsetup luksAddKey /dev/disk/by-partlabel/keystore --key-slot 0 --priority prefer --key-file=$key_in_use
      return $?
      ;;
    *)
      return 1
      ;;
  esac
}

unlock_name_by_keyfile(){
  if [ -e /dev/mapper/keystore ]; then
    tmpdir=$(mktemp -d)
    mkdir -p $tmpdir
    mount /dev/mapper/keystore $tmpdir
    cat $tmpdir/luks-$name.keyfile >&8
    umount $tmpdir
    rm -rf $tmpdir
    cryptsetup close keystore
  fi
}

tpm2_salt_pcr789(){
  tpm2_pcrextend 7:sha256=0x0000000000000000000000000000000000000000000000000000000000000000
  tpm2_pcrextend 8:sha256=0x0000000000000000000000000000000000000000000000000000000000000000
  tpm2_pcrextend 9:sha256=0x0000000000000000000000000000000000000000000000000000000000000000 
}

keystore_refresh_randkey_by_pin(){
  local tmp4rand=$(mktemp -d)
  mkdir -p $tmp4rand

  # add new rand key to luks key slot
  cryptsetup luksKillSlot /dev/disk/by-partlabel/keystore 2 -q
  local new_rand_key=$tmp4rand/luks-keystore.keyfile
  openssl rand -out $new_rand_key 128
  plymouth ask-for-password --prompt "Enter PIN to update TPM" --number-of-tries=2 --command="cryptsetup luksAddKey /dev/disk/by-partlabel/keystore $new_rand_key --key-slot=2 --key-file=-"
  cryptsetup open /dev/disk/by-partlabel/keystore keystore --key-slot 2 --priority prefer --key-file=$new_rand_key

  # persist new key to tpm
  tpm2_evictcontrol --hierarchy o --object-context $tpm_obj
  tpm2_startauthsession --session $tmp4rand/session.ctx
  tpm2_policypcr --session $tmp4rand/session.ctx --pcr-list sha256:7,8,9 --policy $tmp4rand/pcr_sha256_789.policy
  tpm2_flushcontext $tmp4rand/session.ctx
  rm -f $tmp4rand/session.ctx
  tpm2_createprimary --hierarchy o --hash-algorithm sha256 --key-algorithm rsa --key-context $tmp4rand/prim.ctx
  tpm2_create --parent-context $tmp4rand/prim.ctx --hash-algorithm sha256 --public $tmp4rand/pcr_seal_key.pub --private $tmp4rand/pcr_seal_key.priv --sealing-input $new_rand_key --policy $tmp4rand/pcr_sha256_789.policy
  tpm2_load -C $tmp4rand/prim.ctx -u $tmp4rand/pcr_seal_key.pub -r $tmp4rand/pcr_seal_key.priv -n $tmp4rand/pcr_seal_key.name -c $tmp4rand/pcr_seal_key.ctx
  tpm2_flushcontext --transient
  tpm2_evictcontrol --hierarchy o --object-context $tmp4rand/pcr_seal_key.ctx $tpm_obj
  [ $? -eq 0 ] && {
    cryptsetup luksKillSlot /dev/disk/by-partlabel/keystore 0 -q
  } || {
    manipulate_keystore_with_hwid "prepare" "$new_rand_key"
    cryptsetup luksKillSlot /dev/disk/by-partlabel/keystore 2 -q
    return 2
  }
  tpm2_flushcontext --transient
  rm -rf $tmp4rand
  return 0
}

# keystore luks key slots:
# 0: hwid
# 1: pin
# 2: rand --> persist to TPM
{
  flock -s 9
  if tpm2_getcap handles-persistent | grep $tpm_obj > /dev/null; then
    unlock_keystore_by_tpm
    [ ! -e /dev/mapper/keystore ] && {
      keystore_refresh_randkey_by_pin
      [ $? -ne 0 ] && manipulate_keystore_with_hwid "unlock"
    }
    tpm2_salt_pcr789
  else
    manipulate_keystore_with_hwid "unlock"
    [ $? -ne 0 ] && manipulate_keystore_with_hwid "fallback"
  fi
  unlock_name_by_keyfile
} 9>$logout.lock

# redirect console
exec 1<&8
exec 2<&9
