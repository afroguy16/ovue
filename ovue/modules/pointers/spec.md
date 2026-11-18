# Pointer storage transition

Author: Okoro (AI Agent)
Human Driver: Jonathan

This directory now contains only the existing SQLite implementation for pointer data. The pointer operation boundary is documented in [`ovue/operations/spec.md`](../../operations/spec.md), and the complete behavior contract remains in the repository-level [`spec.md`](../../../spec.md).

This storage code will move to the top-level `ovue/storage/` package in the persistence slice. Until then, it remains the implementation used by the operations package. Do not add new pointer operations here.
