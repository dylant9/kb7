.PHONY: check test studio-check firmware-check

check: test studio-check firmware-check
	python3 tools/check_public_tree.py .

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pc_app python3 -m unittest discover -s pc_app/tests -v

studio-check:
	node --check pc_app/web/app.js

firmware-check:
	$(MAKE) -C replacement_fw clean all
	$(MAKE) -C replacement_fw clean
