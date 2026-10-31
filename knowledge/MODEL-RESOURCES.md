# Model resources

The default knowledge configuration binds no user CAD model, template, material library
or shared directory. The index itself contains navigation documents, not model geometry.
Historical engineering inputs and stopped instances are evidence to preserve, not an
automatic source of a new task's models or connection settings.

Locate the CLI resource root as the parent of the default index.json's `knowledge`
directory: the repository root in source, or `<engineer-package-root>/cli` in a delivery.
The optional default external file is `knowledge.local.json` under that resource root;
an explicitly selected external file resolves its entries from its own directory.
The outer engineer-package README directory is not the default index's base.

For an authorized task, the user may supply a versioned catalogue through the external
knowledge configuration. Its records should identify each resource's name, purpose,
actual path/URL, exact file/model revision, units, applicable Creo version and read method.
Record the resource's permission/licensing limits and actual input identity when used.
Do not bundle vendor or user resources whose redistribution rights are not established.

Reading a catalogue does not authorize opening any listed CAD model. Use only the actual
task's declared owned input and current scope. Do not recursively scan a directory,
use a development-checkout fallback, open a historical stopped model, overwrite the
original input or infer that a missing path is equivalent to a nearby model.

Missing files, inaccessible shares and permission refusal remain explicit. No automatic
login, upload, permission escalation or replacement-model generation is provided.
