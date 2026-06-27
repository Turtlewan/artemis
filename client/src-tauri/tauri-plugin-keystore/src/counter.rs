use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use crate::error::KeystoreError;

/// Crash-safe monotonic counter persisted outside the hardware key.
///
/// Missing or corrupt files fail closed. Only `reset_for_new_key` may create a fresh zero counter
/// after the old device key has been invalidated.
#[derive(Debug, Clone)]
pub struct CounterStore {
    path: PathBuf,
}

impl CounterStore {
    pub fn new(app_data_dir: PathBuf) -> Self {
        Self {
            path: app_data_dir.join("keystore").join("counter"),
        }
    }

    pub fn reset_for_new_key(&self) -> Result<(), KeystoreError> {
        self.persist(0)
    }

    pub fn next(&self) -> Result<u64, KeystoreError> {
        let current = self.load()?;
        let next = current.checked_add(1).ok_or(KeystoreError::Encoding)?;
        self.persist(next)?;
        Ok(next)
    }

    fn load(&self) -> Result<u64, KeystoreError> {
        let mut file = File::open(&self.path).map_err(|_| KeystoreError::Encoding)?;
        let mut bytes = [0u8; 8];
        file.read_exact(&mut bytes)
            .map_err(|_| KeystoreError::Encoding)?;
        let mut extra = [0u8; 1];
        if file.read(&mut extra).map_err(|_| KeystoreError::Encoding)? != 0 {
            return Err(KeystoreError::Encoding);
        }
        Ok(u64::from_be_bytes(bytes))
    }

    fn persist(&self, value: u64) -> Result<(), KeystoreError> {
        let parent = self.path.parent().ok_or(KeystoreError::Encoding)?;
        fs::create_dir_all(parent).map_err(|_| KeystoreError::Encoding)?;
        let temp_path = temp_path(&self.path);
        {
            let mut temp = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(&temp_path)
                .map_err(|_| KeystoreError::Encoding)?;
            temp.write_all(&value.to_be_bytes())
                .map_err(|_| KeystoreError::Encoding)?;
            temp.sync_all().map_err(|_| KeystoreError::Encoding)?;
        }
        fs::rename(&temp_path, &self.path).map_err(|_| KeystoreError::Encoding)?;
        sync_dir(parent)?;
        Ok(())
    }
}

fn temp_path(path: &Path) -> PathBuf {
    path.with_extension("tmp")
}

fn sync_dir(path: &Path) -> Result<(), KeystoreError> {
    #[cfg(windows)]
    {
        let _ = path;
        Ok(())
    }
    #[cfg(not(windows))]
    {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| KeystoreError::Encoding)
    }
}
