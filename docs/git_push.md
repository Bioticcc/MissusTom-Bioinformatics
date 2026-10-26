# Instructions for our Git and release workflow

Use SSH for this repository. Check that GitHub access works before starting:

```bash
git remote -v
gh auth status
ssh -T git@github.com
```

## 1. Test manually

```bash
./scripts/dev-backend.sh
cd desktop
npm run tauri dev
```

For a release, also run the complete automated check from the repository root:

```bash
cd ..
./scripts/check.sh
```

## 2. Choose and apply the release version

Check the latest tag first. A stable release uses the next stable SemVer version, such as `v0.4.5`; a release candidate uses an existing SemVer prerelease form, such as `v0.4.5-rc.1`.

```bash
git fetch origin --tags
git tag --list 'v*' --sort=-v:refname | head
```
Use the version-update script instead of editing these fields by hand:

```bash
./scripts/update-release-version.sh v0.4.5
```

## 3. Create and push the release commit

Note: I use git add . for most things, but if you want to push specific files, be sure to NOT do git add . here, as it will just commit every single changed file not in the gitignore. 

```bash
git status --short
git add .
git commit -m "Missus Tom v0.4.5: BRS Learn and Modify scripts readability improved"
git push origin main
git rev-parse HEAD
```

## 4. Create the release

```bash
git fetch origin --tags
git tag -a v0.4.5 <commit-sha> -m "Missus Tom v0.4.5: BRS Learn and Modify scripts readability improved"
git push origin v0.4.5
```

