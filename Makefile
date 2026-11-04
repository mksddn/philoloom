.PHONY: build serve images check
build: images
	python3 scripts/build.py
serve: build
	python3 -m http.server 8000 --bind 127.0.0.1 --directory dist

images:
	python3 scripts/optimize_images.py

check: build
	python3 -m unittest discover -s tests -v
