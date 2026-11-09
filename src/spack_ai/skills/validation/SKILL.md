### Validation (`validate_recipe`)

Validate after every substantive recipe change and before you call the work done.
Fix every `error`. Report remaining `warning`s, and FIXMEs in particular, to the user
rather than hiding them. Concretization (`spack spec`) only runs when Spack is installed
and an environment exists, so generate the environment first if you want it.
