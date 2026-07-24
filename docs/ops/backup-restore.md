# Backup restore

Status: Current

1. Record the source volume, snapshot ID/time, deployed release SHA, and
   expected projects.
2. Restore into a separate volume and isolated machine; never overwrite the
   active production volume for a drill.
3. Boot the same application release against the restored volume.
4. Open an owned test project and export both PDF and CBZ.
5. Verify project isolation and record missing/corrupt artifacts.
6. Destroy the isolated drill resources after retaining non-sensitive
   evidence.

A configured snapshot schedule is not a completed backup control until this
drill passes.
