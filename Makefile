.PHONY: check test studio-check firmware-check hardware-check

check: test studio-check firmware-check hardware-check
	python3 tools/check_public_tree.py .
	python3 tools/audit_firmware_source.py .

test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pc_app python3 -m unittest discover -s pc_app/tests -v

studio-check:
	node --check pc_app/web/app.js
	node pc_app/web/validation-test.js

firmware-check:
	$(MAKE) -C replacement_fw clean all
	$(MAKE) -C replacement_fw audit-profile
	$(MAKE) -C replacement_fw integration-check
	$(MAKE) -C replacement_fw recovery-proof
	$(MAKE) -C replacement_fw region1-reentry-proof
	$(MAKE) -C replacement_fw clean

hardware-check:
	python3 tools/check_hardware_facts.py
